"""The worker side of one durable tool call.

Looks up the registered body, builds the turn context the host supplies,
runs the body, persists the result on the ``background_tasks`` row and opens
the turn that answers the parked call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import procrastinate
from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic import BaseModel

from assistant_core.conversation.event_writer import append_chunk
from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.stream_events import task_completed_event
from assistant_core.graph.turn_state import DurableTaskResult
from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.memory.store import MemoryStore
from assistant_core.models.capture import capture_llm
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
)
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import get_logger
from assistant_core.platform.types import JSONObject
from assistant_core.tasks.completion_turn import safe_completion_turn
from assistant_core.tasks.declaration import (
    DurableTool,
    declared_durable_tools,
    durable_impl,
)
from assistant_core.tasks.job_context import durable_job_context
from assistant_core.tasks.names import DURABLE_TASK_QUEUE
from assistant_core.tasks.progress import TaskProgressEmitter
from assistant_core.tasks.redaction import install_job_payload_redaction
from assistant_core.tasks.scope import (
    attach_conversation_application,
    attach_user_id,
)

logger = get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class WorkerContextRequest:
    """What the runtime knows before the host builds the body's turn context."""

    conversation_id: UUID
    task_id: UUID
    memory_store: AsyncPostgresStore


type WorkerContextFactory = Callable[[WorkerContextRequest], Awaitable[TurnContext]]


class WorkerContextNotInstalledError(RuntimeError):
    """A durable body ran before a host said how to build its turn context."""

    def __init__(self) -> None:
        super().__init__(
            "no worker context is installed: call "
            "install_worker_context(build) with the host's context factory",
        )


class _InstalledWorkerContext:
    """How this process builds the turn context a durable body reads."""

    def __init__(self) -> None:
        self._build: WorkerContextFactory | None = None

    def install(self, build: WorkerContextFactory) -> None:
        self._build = build

    def reset(self) -> None:
        self._build = None

    def read(self) -> WorkerContextFactory:
        if self._build is None:
            raise WorkerContextNotInstalledError
        return self._build


_installed = _InstalledWorkerContext()


def install_worker_context(build: WorkerContextFactory) -> None:
    """Build a durable body's turn context through the host's factory."""
    _installed.install(build)


def reset_worker_context() -> None:
    """Forget the installed factory, so a process can install another."""
    _installed.reset()


def installed_worker_context() -> WorkerContextFactory:
    """The context factory in force for this process."""
    return _installed.read()


def register_durable_jobs(
    app: procrastinate.App,
    *,
    worker_name: str | None = None,
) -> None:
    """Declare one procrastinate job per declared durable tool.

    The name and the queue come from the declaration, so the job the decorator
    defers is the job the worker consumes. The scrub is attached here because
    this process is the one that logs a durable job's stored kwargs.
    """
    install_job_payload_redaction(worker_name=worker_name)
    for tool in declared_durable_tools():
        _register_one(app, tool)


def _register_one(app: procrastinate.App, tool: DurableTool) -> None:
    async def job(
        task_id: str,
        thread_id: str,
        args: dict[str, Any],
        capture_dir: str | None = None,
        job_context: JSONObject | None = None,
    ) -> None:
        await run_durable_task(
            tool_name=tool.tool_name,
            task_id=task_id,
            thread_id=thread_id,
            args=args,
            capture_dir=capture_dir,
            job_context=job_context or {},
        )

    app.task(queue=DURABLE_TASK_QUEUE, name=tool.job_name)(job)


async def run_durable_task(
    *,
    tool_name: str,
    task_id: str,
    thread_id: str,
    args: dict[str, Any],
    capture_dir: str | None = None,
    job_context: JSONObject | None = None,
) -> None:
    """Run one durable body on the worker and open the completion turn.

    ``capture_dir`` re-installs the run's model capture, so the turn where the
    agent reads the result is recorded with the rest of the run.
    """
    capture = capture_llm(capture_dir) if capture_dir else nullcontext()
    with capture:
        await _run_durable_task_inner(
            tool_name=tool_name,
            task_id=task_id,
            thread_id=thread_id,
            args=args,
            job_context=job_context or {},
        )


async def _run_durable_task_inner(
    *,
    tool_name: str,
    task_id: str,
    thread_id: str,
    args: dict[str, Any],
    job_context: JSONObject,
) -> None:
    task_uuid = UUID(task_id)
    chat_uuid = UUID(thread_id)
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    await repo.mark_running(task_id=task_uuid)

    impl = durable_impl(tool_name)
    if impl is None:
        error = f"unknown durable tool: {tool_name}"
        logger.error("durable runner missing impl", tool_name=tool_name)
        await repo.mark_failed(task_id=task_uuid, error=error)
        await _announce_completion(chat_uuid, task_uuid, "failed", error)
        await _answer_and_settle(
            repo,
            thread_id=thread_id,
            result=DurableTaskResult(task_id=task_uuid, status="failed", error=error),
            fallback=(),
        )
        return

    progress = TaskProgressEmitter(
        task_id=task_uuid,
        conversation_id=chat_uuid,
        session_factory=async_session_factory,
    )

    settings = get_runtime_settings()
    carried = durable_job_context()
    try:
        async with (
            carried.restore(carried.state_type.model_validate(job_context)),
            attach_conversation_application(chat_uuid),
            lifespan_memory_store(settings.database_url) as raw_memory,
        ):
            mem_store = MemoryStore(store=raw_memory)
            context = await installed_worker_context()(
                WorkerContextRequest(
                    conversation_id=chat_uuid,
                    task_id=task_uuid,
                    memory_store=raw_memory,
                ),
            )
            async with attach_user_id(context.user_id):
                try:
                    payload = await impl(
                        context=context,
                        task_id=task_uuid,
                        conversation_id=chat_uuid,
                        progress=progress,
                        memory_store=mem_store,
                        **args.get("kwargs", {}),
                    )
                finally:
                    await progress.aclose()
    except Exception as exc:  # the worker records every failure
        logger.exception("durable tool failed", tool_name=tool_name)
        error = str(exc) or exc.__class__.__name__
        await repo.mark_failed(task_id=task_uuid, error=error)
        await _announce_completion(chat_uuid, task_uuid, "failed", error)
        await _answer_and_settle(
            repo,
            thread_id=thread_id,
            result=DurableTaskResult(task_id=task_uuid, status="failed", error=error),
            fallback=(),
        )
        return

    result = _to_dict(payload)
    await repo.mark_result_ready(task_id=task_uuid, result=result)
    await _announce_completion(chat_uuid, task_uuid, "success", None)
    await _answer_and_settle(
        repo,
        thread_id=thread_id,
        result=DurableTaskResult(task_id=task_uuid, status="success", result=result),
        fallback=(task_uuid,),
    )


async def _answer_and_settle(
    repo: BackgroundTaskRepository,
    *,
    thread_id: str,
    result: DurableTaskResult,
    fallback: tuple[UUID, ...],
) -> None:
    """Open the completion turn, then close the rows it spoke for.

    ``fallback`` is settled when no parked run answered the task: a task whose
    own tool failed is already terminal, so the failure paths pass nothing.
    """
    outcome = await safe_completion_turn(thread_id, result)
    if outcome.waiting:
        return
    for task_id in outcome.answered or fallback:
        if outcome.error:
            await repo.mark_failed(task_id=task_id, error=outcome.error)
        else:
            await repo.mark_complete(task_id=task_id)


async def _announce_completion(
    conversation_id: UUID,
    task_id: UUID,
    status: Literal["success", "failed"],
    error: str | None,
) -> None:
    """Record the tool's outcome on the thread, before the completion turn.

    The status reports whether the tool produced a result. A completion turn
    that then fails reports its own failure.
    """
    await append_chunk(
        conversation_id=conversation_id,
        chunk=task_completed_event(
            task_id=task_id,
            status=status,
            error=error,
        ).model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def _to_dict(value: Any) -> dict[str, Any]:
    """Coerce a body's return into a JSON-serialisable dict.

    A body returns a Pydantic model or a plain dict. Anything else is wrapped
    under ``value`` so the serialised row stays valid JSON.
    """
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


__all__ = [
    "WorkerContextFactory",
    "WorkerContextNotInstalledError",
    "WorkerContextRequest",
    "install_worker_context",
    "installed_worker_context",
    "register_durable_jobs",
    "reset_worker_context",
    "run_durable_task",
]
