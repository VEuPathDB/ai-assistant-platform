"""A durable assistant built only from the runtime's own code.

One tool defers to a worker, the worker runs its body, and the completion
turn re-enters the run that parked the call.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import procrastinate
import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from procrastinate.testing import InMemoryConnector
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, FinishChunk
from tests.conftest import seed_host_user
from tests.synthetic import UsageLedger, dump_chunk

from assistant_core.conversation.checkpointer import (
    lifespan_checkpointer,
    to_psycopg_url,
)
from assistant_core.conversation.event_writer import ChatEventWriter, ChatWriter
from assistant_core.graph.runtime import AssistantDeps, TurnContext
from assistant_core.graph.single_agent import single_agent_graph
from assistant_core.graph.turn_state import TurnState
from assistant_core.models.scripted import (
    called_tool_parts,
    current_turn,
    last_user_text,
    scripted_text,
    tool_return_parts,
)
from assistant_core.persistence.models import Conversation
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.types import JSONObject
from assistant_core.registry import (
    AssistantRegistry,
    install_assistant_registry,
    reset_assistant_registry,
)
from assistant_core.spec import AssistantSpec, TurnContextRequest, TurnStart, turn_input
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.completion_turn import (
    CompletionTurn,
    install_completion_turn,
    reset_completion_turn,
)
from assistant_core.tasks.declaration import (
    DurableTool,
    declare_durable_tool,
    register_durable_impl,
)
from assistant_core.tasks.decorator import durable_tool
from assistant_core.tasks.job_context import (
    DurableJobState,
    install_durable_job_context,
    reset_durable_job_context,
)
from assistant_core.tasks.progress import TaskProgressEmitter
from assistant_core.tasks.runner import (
    WorkerContextRequest,
    install_worker_context,
    register_durable_jobs,
    reset_worker_context,
)

DURABLE_ASSISTANT_ID = "durable"
DURABLE_SITE_ID = "synthetic"
DURABLE_MODE = "chat"

# The queue this host names for its durable work, which is not the default.
HOST_DURABLE_QUEUE = "long_running"

CRUNCH_TOOL = "crunch"
SIFT_TOOL = "sift"

CRUNCH_CALL_ID = "call_crunch"
SIFT_CALL_ID = "call_sift"

ONE_PROMPT = "please crunch"
TWO_PROMPT = "please crunch and sift"

CRUNCH_SECONDS = 90
SIFT_SECONDS = 30


@dataclass
class WorkerRuns:
    """What each durable body was called with, and what it answered."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    restored: list[JSONObject] = field(default_factory=list)
    fail_with: str = ""


class CarriedState(DurableJobState):
    """The one value this host's job context carries onto the worker."""

    token: str = ""


class CarriedJobContext:
    """A host job context that carries one value onto the worker."""

    state_type = CarriedState

    def __init__(self, runs: WorkerRuns, token: str) -> None:
        self._runs = runs
        self._token = token

    def capture(self) -> CarriedState:
        return CarriedState(token=self._token)

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        runs = self._runs

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            runs.restored.append(state.model_dump(mode="json"))
            yield

        return _scope()


@pytest.fixture(scope="session")
async def procrastinate_schema(patch_app_db_engine: None) -> None:
    """Apply the host's queue schema once, so a beat has a row to write."""
    del patch_app_db_engine
    url = to_psycopg_url(get_runtime_settings().database_url)
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=url))
    async with app.open_async():
        await app.schema_manager.apply_schema_async()


@pytest.fixture
def worker_runs() -> WorkerRuns:
    return WorkerRuns()


@pytest.fixture
def durable_tools(
    empty_registry: None,
    worker_runs: WorkerRuns,
) -> tuple[DurableTool, DurableTool]:
    """Two declared durable tools, with the bodies the worker runs."""
    del empty_registry
    crunch = declare_durable_tool(
        tool_name=CRUNCH_TOOL,
        estimated_duration_seconds=CRUNCH_SECONDS,
    )
    sift = declare_durable_tool(
        tool_name=SIFT_TOOL,
        estimated_duration_seconds=SIFT_SECONDS,
    )

    def _body(name: str) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def run(
            *,
            context: TurnContext,
            task_id: UUID,
            conversation_id: UUID,
            progress: TaskProgressEmitter,
            memory_store: object,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del context, memory_store
            worker_runs.calls.append(
                {
                    "tool": name,
                    "task_id": task_id,
                    "conversation_id": conversation_id,
                    "kwargs": kwargs,
                },
            )
            await progress.update(percent=0.5, message=f"{name} halfway")
            if worker_runs.fail_with:
                raise RuntimeError(worker_runs.fail_with)
            return {"tool": name, "counted": kwargs.get("n", 0)}

        return run

    register_durable_impl(crunch, _body(CRUNCH_TOOL))
    register_durable_impl(sift, _body(SIFT_TOOL))
    return crunch, sift


@pytest.fixture
def task_queue(
    durable_tools: tuple[DurableTool, DurableTool],
) -> Iterator[procrastinate.App]:
    """A procrastinate application that keeps its jobs in memory.

    The queue is named here, as a host names it, so the arc covers the name
    reaching both the deferral and the worker.
    """
    del durable_tools
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app, durable_queue=HOST_DURABLE_QUEUE)
    register_durable_jobs(app)
    yield app
    reset_task_app()


@pytest.fixture
def carried_job_context(worker_runs: WorkerRuns) -> Iterator[CarriedJobContext]:
    context = CarriedJobContext(worker_runs, "carried-token")
    install_durable_job_context(context)
    yield context
    reset_durable_job_context()


def _one_or_two(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Two markers: one durable call, or two in one model step."""
    del info
    turn = current_turn(messages)
    if tool_return_parts(turn):
        returned = [part.content for part in tool_return_parts(turn)]
        return ModelResponse(parts=[scripted_text(f"Results: {returned}.")])
    made = {part.tool_name for part in called_tool_parts(turn)}
    if made:
        return ModelResponse(parts=[scripted_text("Done.")])
    if TWO_PROMPT in last_user_text(turn):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=CRUNCH_TOOL,
                    args={"n": 2},
                    tool_call_id=CRUNCH_CALL_ID,
                ),
                ToolCallPart(
                    tool_name=SIFT_TOOL,
                    args={"n": 4},
                    tool_call_id=SIFT_CALL_ID,
                ),
            ],
        )
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=CRUNCH_TOOL,
                args={"n": 2},
                tool_call_id=CRUNCH_CALL_ID,
            ),
        ],
    )


async def _stream(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
    """Stream what ``_one_or_two`` decided, one delta per part."""
    response = _one_or_two(messages, info)
    calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
    if not calls:
        for part in response.parts:
            if isinstance(part, TextPart):
                yield part.content
        return
    yield {
        index: DeltaToolCall(
            name=call.tool_name,
            json_args=call.args_as_json_str(),
            tool_call_id=call.tool_call_id,
        )
        for index, call in enumerate(calls)
    }


def durable_model() -> Model:
    return FunctionModel(_one_or_two, stream_function=_stream)


def _deps(state: TurnState, context: TurnContext) -> AssistantDeps:
    return AssistantDeps(
        site_id=context.site_id,
        user_id=context.user_id,
        conversation_id=state.conversation_id,
        db_session_factory=context.db_session_factory,
        memory_store=context.memory_store,
        cancel_event=context.cancel_event,
    )


def _durable_agent(
    tools: tuple[DurableTool, DurableTool],
) -> Agent[AssistantDeps, str]:
    crunch_declaration, sift_declaration = tools

    @durable_tool(crunch_declaration)
    async def crunch(ctx: RunContext[AssistantDeps], n: int) -> dict[str, Any]:
        """Crunch a number for a long time."""
        del ctx, n
        msg = "the agent-side body never runs"
        raise AssertionError(msg)

    @durable_tool(sift_declaration)
    async def sift(ctx: RunContext[AssistantDeps], n: int) -> dict[str, Any]:
        """Sift a number for a long time."""
        del ctx, n
        msg = "the agent-side body never runs"
        raise AssertionError(msg)

    return Agent(
        durable_model(),
        output_type=str,
        deps_type=AssistantDeps,
        instructions="Answer the user.",
        tools=[crunch, sift],
        name=DURABLE_ASSISTANT_ID,
    )


def durable_spec(
    ledger: UsageLedger,
    tools: tuple[DurableTool, DurableTool],
) -> AssistantSpec:
    def build_graph(
        checkpointer: BaseCheckpointSaver[Any],
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        return single_agent_graph(
            checkpointer=checkpointer,
            state_type=TurnState,
            context_type=TurnContext,
            build_agent=lambda: _durable_agent(tools),
            build_deps=_deps,
            charge_usage=ledger,
        )

    async def build_turn_context(request: TurnContextRequest) -> TurnContext:
        return TurnContext(
            site_id=request.site_id,
            user_id=request.user_id,
            db_session_factory=async_session_factory,
            cancel_event=request.cancel_event,
            memory_store=request.memory_store,
            phase_models=request.phase_models,
            phase_reasoning=request.phase_reasoning,
        )

    return AssistantSpec(
        assistant_id=DURABLE_ASSISTANT_ID,
        build_graph=build_graph,
        build_initial_state=lambda start: TurnState(**start.state_kwargs()),
        build_turn_context=build_turn_context,
        build_mock_model=durable_model,
        checkpoint_types=(TurnState,),
    )


@dataclass(frozen=True, kw_only=True)
class DurableRuntime:
    """One installed durable assistant and the thread its turns run on."""

    spec: AssistantSpec
    graph: CompiledStateGraph[Any, Any, Any, Any]
    conversation_id: UUID
    user_id: UUID
    chunks: list[dict[str, Any]]

    async def run(self, prompt: str) -> UUID:
        """Drive one turn that parks on a durable call. Reports its message id."""
        turn_id = uuid4()
        writer = ChatEventWriter(
            conversation_id=self.conversation_id,
            turn_id=turn_id,
        )
        await self._drive(
            graph=self.graph,
            writer=writer,
            start=TurnStart(
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                site_id=DURABLE_SITE_ID,
                mode=DURABLE_MODE,
                turn_message_id=turn_id,
                turn_start_event_id=0,
                user_message_id=uuid4(),
                user_prompt=prompt,
            ),
        )
        return turn_id

    async def _drive(
        self,
        *,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        writer: ChatWriter,
        start: TurnStart,
    ) -> None:
        context = await self.spec.build_turn_context(
            TurnContextRequest(
                conversation=None,
                site_id=DURABLE_SITE_ID,
                user_id=self.user_id,
                memory_store=None,
                cancel_event=asyncio.Event(),
                phase_models={},
                phase_reasoning={},
            ),
        )
        graph_input = turn_input(self.spec.build_initial_state(start))
        config: dict[str, Any] = {
            "configurable": {"thread_id": str(self.conversation_id)},
        }
        async for _mode, payload in graph.astream(
            graph_input,
            config=config,
            context=context,
            stream_mode=["custom"],
        ):
            chunk = payload["chunk"]
            self.chunks.append(chunk)
            await writer.write(chunk)

    async def answer(self, turn: CompletionTurn) -> None:
        """Drive the turn a finished task opens, as a host would."""
        await self._drive(
            graph=turn.compiled_graph,
            writer=turn.writer,
            start=TurnStart(
                conversation_id=self.conversation_id,
                user_id=turn.user_id,
                site_id=DURABLE_SITE_ID,
                mode=DURABLE_MODE,
                turn_message_id=turn.writer.turn_id,
                turn_start_event_id=0,
                is_resume=True,
                durable_result=turn.durable_result,
                durable_results=turn.durable_results,
            ),
        )
        for chunk in (FinishChunk(finish_reason="stop"), DoneChunk()):
            await turn.writer.write(dump_chunk(chunk))


@pytest.fixture(scope="session")
async def durable_checkpointer(
    patch_app_db_engine: None,
) -> AsyncIterator[AsyncPostgresSaver]:
    del patch_app_db_engine
    async with lifespan_checkpointer(
        os.environ["DATABASE_URL"],
        checkpoint_types=(TurnState,),
    ) as saver:
        yield saver


@pytest.fixture
async def durable_runtime(
    durable_checkpointer: AsyncPostgresSaver,
    durable_tools: tuple[DurableTool, DurableTool],
    task_queue: procrastinate.App,
    db_cleaner: None,
    patch_app_db_engine: None,
) -> AsyncIterator[DurableRuntime]:
    """The durable assistant, installed the way a host installs it."""
    del db_cleaner, patch_app_db_engine, task_queue
    conversation_id, user_id = uuid4(), uuid4()
    await seed_host_user(user_id)
    async with async_session_factory() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                site_id=DURABLE_SITE_ID,
                assistant_id=DURABLE_ASSISTANT_ID,
            ),
        )
        await session.commit()

    spec = durable_spec(UsageLedger(), durable_tools)
    runtime = DurableRuntime(
        spec=spec,
        graph=spec.build_graph(durable_checkpointer),
        conversation_id=conversation_id,
        user_id=user_id,
        chunks=[],
    )
    install_assistant_registry(
        AssistantRegistry(specs=[spec], default_id=DURABLE_ASSISTANT_ID),
    )
    install_completion_turn(runtime.answer)

    async def build_context(request: WorkerContextRequest) -> TurnContext:
        return TurnContext(
            site_id=DURABLE_SITE_ID,
            user_id=user_id,
            db_session_factory=async_session_factory,
            cancel_event=asyncio.Event(),
            memory_store=request.memory_store,
        )

    install_worker_context(build_context)
    yield runtime
    reset_completion_turn()
    reset_worker_context()
    reset_assistant_registry()
    reset_durable_job_context()
