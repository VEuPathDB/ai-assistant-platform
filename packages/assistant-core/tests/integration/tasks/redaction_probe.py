"""One durable job on a real procrastinate worker, run as its own process.

The scenario decides when the process configures logging and what it names its
worker, so each ordering is measured in an interpreter that created no other
procrastinate logger first.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import procrastinate
from procrastinate.testing import InMemoryConnector
from procrastinate.worker import WORKER_NAME, Worker
from pydantic import BaseModel, SecretStr
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import insert
from tests._host_schema import HOST_USERS

from assistant_core.graph.runtime import AssistantDeps, TurnContext
from assistant_core.graph.single_agent import single_agent_graph
from assistant_core.graph.turn_state import TurnState
from assistant_core.persistence.models import Conversation
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import setup_logging
from assistant_core.registry import AssistantRegistry, install_assistant_registry
from assistant_core.spec import AssistantSpec, TurnContextRequest, TurnStart
from assistant_core.tasks.app import durable_task_queue
from assistant_core.tasks.declaration import declare_durable_tool, register_durable_impl
from assistant_core.tasks.job_context import (
    CarriedSecret,
    DurableJobState,
    install_durable_job_context,
)
from assistant_core.tasks.payloads import DurableTaskPayload
from assistant_core.tasks.progress import TaskProgressEmitter
from assistant_core.tasks.runner import (
    WorkerContextRequest,
    install_worker_context,
    register_durable_jobs,
)

MARKER = "WDK-MARKERBYTES-0ff1ce-live-session-cookie"
CUSTOM_WORKER_NAME = "beetle"
PROBE_TOOL = "probe"
PROBE_ASSISTANT = "probe"
PROBE_SITE = "synthetic"
PROBE_SECONDS = 1
PROBE_COUNT = 2


class Scenario(StrEnum):
    """When this process configures logging, and what it names its worker."""

    LOGGING_FIRST = "logging_first"
    LOGGING_AFTER = "logging_after"
    NAMED_WORKER = "named_worker"
    SETUP_LOGGING_AFTER = "setup_logging_after"


class ProbeResult(BaseModel):
    """What one probe process measured, beside the log it wrote to stdout."""

    scenario: Scenario
    worker_logger: str
    job_name: str
    reads: int
    read_matches_marker: bool
    task_status: str
    counted: int


class ProbeState(DurableJobState):
    """The credential this probe's host carries onto the worker."""

    auth_token: CarriedSecret | None = None


class ProbeJobContext:
    """A job context that records every read of the carried credential."""

    state_type = ProbeState

    def __init__(self, reads: list[str]) -> None:
        self._reads = reads

    def capture(self) -> ProbeState:
        return ProbeState(auth_token=SecretStr(MARKER))

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        reads = self._reads

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            carried = ProbeState.model_validate(state.model_dump())
            if carried.auth_token is not None:
                reads.append(carried.auth_token.get_secret_value())
            yield

        return _scope()


async def _body(
    *,
    context: TurnContext,
    task_id: UUID,
    conversation_id: UUID,
    progress: TaskProgressEmitter,
    memory_store: object,
    **kwargs: Any,
) -> dict[str, Any]:
    del context, task_id, conversation_id, progress, memory_store
    return {"counted": kwargs["n"]}


def _deps(state: TurnState, context: TurnContext) -> AssistantDeps:
    return AssistantDeps(
        site_id=context.site_id,
        user_id=context.user_id,
        conversation_id=state.conversation_id,
        db_session_factory=context.db_session_factory,
        memory_store=context.memory_store,
        cancel_event=context.cancel_event,
    )


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart(content="done")])


def _build_model() -> FunctionModel:
    return FunctionModel(_answer)


def _build_agent() -> Agent[AssistantDeps, str]:
    return Agent(
        _build_model(),
        output_type=str,
        deps_type=AssistantDeps,
        instructions="Answer the user.",
        name=PROBE_ASSISTANT,
    )


async def _charge(user_id: UUID, tokens: int, cost_usd: Decimal) -> None:
    del user_id, tokens, cost_usd


async def _build_turn_context(request: TurnContextRequest) -> TurnContext:
    return TurnContext(
        site_id=request.site_id,
        user_id=request.user_id,
        db_session_factory=async_session_factory,
        cancel_event=request.cancel_event,
        memory_store=request.memory_store,
    )


def _initial_state(start: TurnStart) -> TurnState:
    return TurnState(**start.state_kwargs())


def _probe_spec() -> AssistantSpec:
    """The assistant the completion turn resolves for this thread."""
    return AssistantSpec(
        assistant_id=PROBE_ASSISTANT,
        build_graph=lambda checkpointer: single_agent_graph(
            checkpointer=checkpointer,
            state_type=TurnState,
            context_type=TurnContext,
            build_agent=_build_agent,
            build_deps=_deps,
            charge_usage=_charge,
        ),
        build_initial_state=_initial_state,
        build_turn_context=_build_turn_context,
        build_mock_model=_build_model,
        checkpoint_types=(TurnState,),
    )


def _log_to_stdout() -> None:
    """Send every record this process emits to stdout, the way a host does."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def worker_name(scenario: Scenario) -> str:
    """What this scenario's process names its worker."""
    if scenario is Scenario.LOGGING_FIRST or scenario is Scenario.LOGGING_AFTER:
        return WORKER_NAME
    return CUSTOM_WORKER_NAME


def _registered_worker_name(scenario: Scenario) -> str | None:
    """The name the registration hears, which one scenario keeps from it."""
    if scenario is Scenario.NAMED_WORKER:
        return CUSTOM_WORKER_NAME
    return None


def _configure_logging(scenario: Scenario) -> None:
    if scenario is Scenario.SETUP_LOGGING_AFTER:
        setup_logging()
        return
    _log_to_stdout()


async def _seed_thread(conversation_id: UUID, user_id: UUID) -> None:
    async with async_session_factory() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                site_id=PROBE_SITE,
                assistant_id=PROBE_ASSISTANT,
            ),
        )
        await session.commit()


async def run(scenario: Scenario) -> ProbeResult:
    """Defer one durable job, run a real worker over it, report what happened."""
    reads: list[str] = []
    conversation_id, user_id = uuid4(), uuid4()
    await _seed_thread(conversation_id, user_id)

    if scenario is Scenario.LOGGING_FIRST:
        _configure_logging(scenario)

    tool = declare_durable_tool(
        tool_name=PROBE_TOOL,
        estimated_duration_seconds=PROBE_SECONDS,
    )
    register_durable_impl(tool, _body)
    install_durable_job_context(ProbeJobContext(reads))
    install_assistant_registry(
        AssistantRegistry(specs=[_probe_spec()], default_id=PROBE_ASSISTANT),
    )

    async def build_context(request: WorkerContextRequest) -> TurnContext:
        return TurnContext(
            site_id=PROBE_SITE,
            user_id=user_id,
            db_session_factory=async_session_factory,
            cancel_event=asyncio.Event(),
            memory_store=request.memory_store,
        )

    install_worker_context(build_context)

    app = procrastinate.App(connector=InMemoryConnector(), import_paths=[])
    register_durable_jobs(app, worker_name=_registered_worker_name(scenario))

    if scenario is not Scenario.LOGGING_FIRST:
        _configure_logging(scenario)

    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    task_id = await repo.create(
        task=NewBackgroundTask(
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name=PROBE_TOOL,
            tool_call_id="call_probe",
            args={"n": PROBE_COUNT},
            estimated_duration_seconds=PROBE_SECONDS,
            phase_overrides={},
        ),
    )
    payload = DurableTaskPayload.from_context(
        task_id=task_id,
        thread_id=conversation_id,
        args={"kwargs": {"n": PROBE_COUNT}},
    )

    async with app.open_async():
        await app.configure_task(name=tool.job_name).defer_async(
            **payload.model_dump(mode="json", by_alias=True),
        )
        worker = Worker(
            app=app,
            queues=[durable_task_queue()],
            name=worker_name(scenario),
            concurrency=1,
            wait=False,
            listen_notify=False,
            install_signal_handlers=False,
        )
        await worker.run()

    finished = await repo.get(task_id=task_id)
    return ProbeResult(
        scenario=scenario,
        worker_logger=worker.logger.name,
        job_name=tool.job_name,
        reads=len(reads),
        read_matches_marker=reads == [MARKER],
        task_status="" if finished is None else finished.status,
        counted=0 if finished is None else int(finished.result["counted"]),
    )


def main(argv: list[str]) -> None:
    result = asyncio.run(run(Scenario(argv[1])))
    Path(argv[2]).write_text(result.model_dump_json())


if __name__ == "__main__":
    main(sys.argv)
