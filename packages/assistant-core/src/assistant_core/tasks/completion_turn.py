"""The turn a finished durable task opens on its thread.

Reads the parked durable call off the checkpoint, gathers every parked task's
answer, and hands the host the turn that re-enters the run that deferred them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore

from assistant_core.conversation.authz import (
    conversation_assistant_id,
    conversation_owner_id,
)
from assistant_core.conversation.checkpointer import lifespan_checkpointer
from assistant_core.conversation.event_writer import ChatEventWriter, ChatWriter
from assistant_core.graph.turn_state import DurableTaskResult, PendingDurableCall
from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    TaskOutcome,
)
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.context import PhaseOverrides
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import get_logger
from assistant_core.registry import assistant_registry
from assistant_core.spec import AssistantSpec
from assistant_core.tasks.scope import attach_conversation_application, attach_user_id

logger = get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class CompletionTurn:
    """One turn a finished durable task opens, as the host runs it."""

    spec: AssistantSpec
    compiled_graph: CompiledStateGraph[Any, Any, Any, Any]
    memory_store: AsyncPostgresStore
    writer: ChatWriter
    conversation_id: UUID
    user_id: UUID
    phase_overrides: PhaseOverrides
    durable_result: DurableTaskResult
    durable_results: tuple[DurableTaskResult, ...]


type OpenCompletionTurn = Callable[[CompletionTurn], Awaitable[None]]


class CompletionTurnNotInstalledError(RuntimeError):
    """A task finished before a host said how to open the turn that answers it."""

    def __init__(self) -> None:
        super().__init__(
            "no completion turn is installed: call install_completion_turn(run) "
            "with the host's turn driver",
        )


class _InstalledCompletionTurn:
    """How this process opens the turn a finished task answers."""

    def __init__(self) -> None:
        self._open: OpenCompletionTurn | None = None

    def install(self, open_turn: OpenCompletionTurn) -> None:
        self._open = open_turn

    def reset(self) -> None:
        self._open = None

    def read(self) -> OpenCompletionTurn:
        if self._open is None:
            raise CompletionTurnNotInstalledError
        return self._open


_installed = _InstalledCompletionTurn()


def install_completion_turn(open_turn: OpenCompletionTurn) -> None:
    """Open a finished task's turn through the host's turn driver."""
    _installed.install(open_turn)


def reset_completion_turn() -> None:
    """Forget the installed driver, so a process can install another."""
    _installed.reset()


def installed_completion_turn() -> OpenCompletionTurn:
    """The turn driver in force for this process."""
    return _installed.read()


@dataclass(frozen=True)
class CompletionOutcome:
    """What opening the completion turn did, so the rows can be settled.

    ``answered`` names the tasks the turn delivered whose tools succeeded; a
    task whose tool failed is already terminal. ``waiting`` marks a run that
    owes results for calls whose tasks have not reported, so its rows keep
    their results until the last one arrives.
    """

    answered: tuple[UUID, ...] = ()
    waiting: bool = False
    error: str = ""


def _turn_failure(exc: Exception) -> str:
    """What a failed completion turn writes on ``background_tasks.error``.

    It names the exception class and its message, so the user reads something
    actionable rather than "something went wrong".
    """
    return f"completion turn failed: {exc.__class__.__name__}: {exc}"


async def safe_completion_turn(
    thread_id: str,
    result: DurableTaskResult,
) -> CompletionOutcome:
    """Open the completion turn and report what it did."""
    try:
        return await _run_completion_turn(thread_id=thread_id, result=result)
    except Exception as exc:
        logger.exception(
            "durable completion turn failed",
            thread_id=thread_id,
            task_id=str(result.task_id),
        )
        return CompletionOutcome(error=_turn_failure(exc))


def _parked_turn_message_id(snapshot: Any) -> UUID:
    raw = snapshot.values.get("turn_message_id")
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        return UUID(raw)
    msg = "checkpoint snapshot missing turn_message_id"
    raise RuntimeError(msg)


def _parked_durable_call(snapshot: Any) -> PendingDurableCall | None:
    """The durable calls the thread parked, when it still waits on one."""
    parked = snapshot.values.get("pending_durable_call")
    if parked is None:
        return None
    return PendingDurableCall.model_validate(parked)


def _as_result(outcome: TaskOutcome) -> DurableTaskResult:
    """One task row's outcome, as the answer a parked call resumes with."""
    if outcome.failed:
        return DurableTaskResult(
            task_id=outcome.id,
            status="failed",
            error=outcome.error,
        )
    return DurableTaskResult(
        task_id=outcome.id,
        status="success",
        result=outcome.result,
    )


async def _gathered_answers(
    repo: BackgroundTaskRepository,
    parked: PendingDurableCall,
    result: DurableTaskResult,
) -> list[DurableTaskResult] | None:
    """Every parked task's answer, or ``None`` while one has not reported.

    One model step can hand several calls to the worker, and pydantic-ai needs
    a result for each call of the response the run re-enters, so the turn opens
    only once the last task reports.
    """
    reported = await repo.reported_outcomes(task_ids=parked.task_ids)
    answers = {task_id: _as_result(found) for task_id, found in reported.items()}
    answers[result.task_id] = result
    if any(task_id not in answers for task_id in parked.task_ids):
        return None
    return [answers[task_id] for task_id in parked.task_ids]


async def _completion_overrides(*, task_id: UUID) -> PhaseOverrides:
    """The per-role picks the completion turn runs under.

    The picks are request-scoped and the request that made them is gone, so
    they are read back from the row the deferring turn wrote.
    """
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    task = await repo.get(task_id=task_id)
    return PhaseOverrides.model_validate({} if task is None else task.phase_overrides)


async def _run_completion_turn(
    *,
    thread_id: str,
    result: DurableTaskResult,
) -> CompletionOutcome:
    """Open a new turn that answers the durable calls the thread parked.

    The turn carries every parked task's result into the run that deferred
    them, so nothing before the calls runs a second time. It writes under the
    parked turn's message id, so the answers patch the tool parts the
    suspending turn left behind.
    """
    settings = get_runtime_settings()
    registry = assistant_registry()
    conversation_id = UUID(thread_id)
    assistant_id = await conversation_assistant_id(conversation_id)
    if assistant_id is None:
        logger.info("no conversation to answer", thread_id=thread_id)
        return CompletionOutcome()
    spec = registry.resolve(assistant_id)
    async with (
        attach_conversation_application(conversation_id),
        lifespan_checkpointer(
            settings.database_url,
            checkpoint_types=registry.checkpoint_types(),
        ) as saver,
        lifespan_memory_store(settings.database_url) as store,
    ):
        graph = spec.build_graph(saver)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        parked = _parked_durable_call(snapshot)
        if parked is None or not parked.owns(result.task_id):
            logger.info(
                "no parked durable call to answer",
                thread_id=thread_id,
                task_id=str(result.task_id),
            )
            return CompletionOutcome()
        repo = BackgroundTaskRepository(session_factory=async_session_factory)
        answers = await _gathered_answers(repo, parked, result)
        if answers is None:
            logger.info(
                "durable calls still running; the turn waits for the last one",
                thread_id=thread_id,
                task_id=str(result.task_id),
                parked=len(parked.durable_calls),
            )
            return CompletionOutcome(waiting=True)
        user_id = await conversation_owner_id(conversation_id)
        if user_id is None:
            logger.info("no owner to answer as", thread_id=thread_id)
            return CompletionOutcome()
        writer = ChatEventWriter(
            conversation_id=conversation_id,
            turn_id=_parked_turn_message_id(snapshot),
        )
        overrides = await _completion_overrides(task_id=result.task_id)
        delivered = tuple(
            answer.task_id for answer in answers if answer.status == "success"
        )
        for task_id in delivered:
            await repo.mark_resuming(task_id=task_id)
        try:
            async with attach_user_id(user_id):
                await installed_completion_turn()(
                    CompletionTurn(
                        spec=spec,
                        compiled_graph=graph,
                        memory_store=store,
                        writer=writer,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        phase_overrides=overrides,
                        durable_result=result,
                        durable_results=tuple(answers),
                    ),
                )
        except Exception as exc:  # every answered row still has to be closed
            logger.exception(
                "durable completion turn failed",
                thread_id=thread_id,
                task_id=str(result.task_id),
            )
            return CompletionOutcome(answered=delivered, error=_turn_failure(exc))
    return CompletionOutcome(answered=delivered)


__all__ = [
    "CompletionOutcome",
    "CompletionTurn",
    "CompletionTurnNotInstalledError",
    "OpenCompletionTurn",
    "install_completion_turn",
    "installed_completion_turn",
    "reset_completion_turn",
    "safe_completion_turn",
]
