"""A complete assistant built only from the runtime's own code.

Every arc the suite drives runs through this spec, so an assertion that holds
here is an assertion about the runtime and nothing else. The application owns
the turn driver; ``drive_turn`` is the smallest composition the package's
public surfaces allow, and it is where the boundary cuts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import ModelMessage, ToolCallPart, ToolReturn
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.ui.vercel_ai.request_types import ToolApprovalResponded
from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    DoneChunk,
    FinishChunk,
    StartChunk,
)

from assistant_core.capabilities.repetition_guard import ToolRepetitionGuard
from assistant_core.conversation.event_writer import ChatEventWriter, ChatWriter
from assistant_core.graph.runtime import AssistantDeps, TurnContext
from assistant_core.graph.single_agent import single_agent_graph
from assistant_core.graph.stream_events import (
    tool_summary_event,
    turn_status_event,
    turn_stopped_event,
)
from assistant_core.graph.turn_state import TurnState
from assistant_core.mcp.declaration import ToolSourceDeclarations
from assistant_core.models.scripted import (
    RoleMarkers,
    ScriptedModel,
    ScriptedPart,
    called_tool_parts,
    current_turn,
    last_user_text,
    scripted_text,
    tool_return_parts,
    user_texts,
)
from assistant_core.platform.db import async_session_factory
from assistant_core.spec import (
    AssistantSpec,
    TurnContextRequest,
    TurnStart,
    turn_input,
)

SYNTHETIC_ASSISTANT_ID = "synthetic"
SYNTHETIC_SITE_ID = "synthetic"
SYNTHETIC_MODE = "chat"

ADD_TOOL = "add"
APPROVAL_TOOL = "wipe_everything"
STOP_TOOL = "stop_turn"
LOOP_TOOL = "peek"

ADD_CALL_ID = "call_add"
APPROVAL_CALL_ID = "call_wipe"
STOP_CALL_ID = "call_stop"
LOOP_CALL_ID = "call_peek"

# A marker in the user's message picks the arc, so a prompt is the script.
ADD_PROMPT = "please add"
APPROVAL_PROMPT = "please wipe"
STOP_PROMPT = "please stop"
LOOP_PROMPT = "please peek"
PLAIN_PROMPT = "which sites do you serve"

# The recall arc answers from the thread, so it is empty until a turn 2.
RECALL_PROMPT = "what did I ask for first"
RECALL_PREFIX = "You first asked: "

# The tools a declared MCP source contributes, under its local name's prefix.
SOURCE_READ_TOOL = "catalog_read_thing"
SOURCE_WRITE_TOOL = "catalog_write_thing"
SOURCE_PLAIN_TOOL = "catalog_plain_thing"

SOURCE_READ_CALL_ID = "call_source_read"
SOURCE_WRITE_CALL_ID = "call_source_write"
SOURCE_PLAIN_CALL_ID = "call_source_plain"

SOURCE_READ_PROMPT = "please read"
SOURCE_WRITE_PROMPT = "please write"
SOURCE_PLAIN_PROMPT = "please look"

SOURCE_THING_NAME = "kinase"

# The loop arc asks for the same reading more times than the guard allows.
LOOP_CALLS = 5

PREPARING_LABEL = "Preparing context"
EPILOGUE_LABEL = "Turn recorded"


async def add(ctx: RunContext[AssistantDeps], a: int, b: int) -> ToolReturn[int]:
    """Add two numbers."""
    total = a + b
    call_id = ctx.tool_call_id
    if call_id is None:
        return ToolReturn(return_value=total)
    return ToolReturn(
        return_value=total,
        metadata=[
            tool_summary_event(
                tool_call_id=call_id,
                summary=f"{a} plus {b} is {total}",
            ),
        ],
    )


async def wipe_everything(target: str) -> str:
    """Delete everything under a target."""
    return f"wiped {target}"


async def peek() -> str:
    """Read a value that never changes."""
    return "unchanged"


async def stop_turn(ctx: RunContext[AssistantDeps]) -> str:
    """Stop the turn that is running."""
    cancel = ctx.deps.cancel_event
    if cancel is not None:
        cancel.set()
    return "stopping"


@dataclass(frozen=True)
class _Arc:
    """One scripted branch: the marker that selects it and the call it makes."""

    marker: str
    tool_name: str
    call_id: str
    args: dict[str, Any]


_ARCS: tuple[_Arc, ...] = (
    _Arc(ADD_PROMPT, ADD_TOOL, ADD_CALL_ID, {"a": 2, "b": 3}),
    _Arc(APPROVAL_PROMPT, APPROVAL_TOOL, APPROVAL_CALL_ID, {"target": "everything"}),
    _Arc(STOP_PROMPT, STOP_TOOL, STOP_CALL_ID, {}),
    _Arc(
        SOURCE_READ_PROMPT,
        SOURCE_READ_TOOL,
        SOURCE_READ_CALL_ID,
        {"name": SOURCE_THING_NAME},
    ),
    _Arc(
        SOURCE_WRITE_PROMPT,
        SOURCE_WRITE_TOOL,
        SOURCE_WRITE_CALL_ID,
        {"name": SOURCE_THING_NAME},
    ),
    _Arc(SOURCE_PLAIN_PROMPT, SOURCE_PLAIN_TOOL, SOURCE_PLAIN_CALL_ID, {}),
)


def _loop_part(messages: list[ModelMessage]) -> ScriptedPart:
    """Ask for the same reading again, under a fresh call id each time."""
    made = [p for p in called_tool_parts(messages) if p.tool_name == LOOP_TOOL]
    if len(made) >= LOOP_CALLS:
        return scripted_text("Nothing changed.")
    return ToolCallPart(
        tool_name=LOOP_TOOL,
        args={},
        tool_call_id=f"{LOOP_CALL_ID}_{len(made)}",
    )


def _next_part(messages: list[ModelMessage]) -> ScriptedPart:
    turn = current_turn(messages)
    text = last_user_text(turn)
    if RECALL_PROMPT in text:
        return scripted_text(f"{RECALL_PREFIX}{user_texts(messages)[0]}")
    if LOOP_PROMPT in text:
        return _loop_part(turn)
    called = {part.tool_name for part in called_tool_parts(turn)}
    for arc in _ARCS:
        if arc.marker in text and arc.tool_name not in called:
            return ToolCallPart(
                tool_name=arc.tool_name,
                args=arc.args,
                tool_call_id=arc.call_id,
            )
    returns = tool_return_parts(turn)
    if returns:
        return scripted_text(f"Result: {returns[-1].content}.")
    return scripted_text(f"You said: {text}")


def synthetic_model() -> ScriptedModel:
    return ScriptedModel(
        roles=(RoleMarkers(role="answerer", markers=frozenset({ADD_TOOL})),),
        scripts={"answerer": _next_part},
        unknown=_next_part,
        model_name="synthetic:scripted",
    )


def synthetic_agent(
    toolsets: Sequence[AbstractToolset[AssistantDeps]] = (),
) -> Agent[AssistantDeps, str]:
    return Agent(
        synthetic_model().as_function_model(),
        output_type=str,
        deps_type=AssistantDeps,
        instructions="Answer the user.",
        tools=[add, Tool(wipe_everything, requires_approval=True), stop_turn, peek],
        toolsets=list(toolsets),
        name=SYNTHETIC_ASSISTANT_ID,
    )


@dataclass
class UsageLedger:
    """What the runtime charged, in the order it charged it."""

    charges: list[tuple[UUID, int, Decimal]] = field(default_factory=list)

    async def __call__(self, user_id: UUID, tokens: int, cost_usd: Decimal) -> None:
        self.charges.append((user_id, tokens, cost_usd))

    @property
    def total_tokens(self) -> int:
        return sum(tokens for _user, tokens, _cost in self.charges)


def _deps(state: TurnState, context: TurnContext) -> AssistantDeps:
    return AssistantDeps(
        site_id=context.site_id,
        user_id=context.user_id,
        conversation_id=state.conversation_id,
        db_session_factory=context.db_session_factory,
        memory_store=context.memory_store,
        cancel_event=context.cancel_event,
        retrieved_memories=state.retrieved_memories,
        tool_repetition_guard=ToolRepetitionGuard(
            read_only_tools=frozenset({LOOP_TOOL}),
        ),
    )


async def _epilogue(conversation_id: UUID) -> list[dict[str, Any]]:
    """The chunks this assistant appends once its graph has finished."""
    del conversation_id
    return [dump_chunk(turn_status_event(label=EPILOGUE_LABEL))]


@dataclass(frozen=True, kw_only=True)
class SyntheticTurnContext(TurnContext):
    """The runtime's turn context, plus the sources this turn resolved."""

    tool_sources: Mapping[str, AbstractToolset[Any]] = field(default_factory=dict)


def synthetic_tool_sources(
    context: TurnContext,
) -> Mapping[str, AbstractToolset[Any]]:
    """The tool sources the synthetic assistant's turn context carries."""
    assert isinstance(context, SyntheticTurnContext)
    return context.tool_sources


def synthetic_graph(
    *,
    checkpointer: BaseCheckpointSaver[Any],
    ledger: UsageLedger,
    toolsets: Sequence[AbstractToolset[AssistantDeps]] = (),
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the synthetic turn graph, with this turn's sources on the agent."""
    return single_agent_graph(
        checkpointer=checkpointer,
        state_type=TurnState,
        context_type=SyntheticTurnContext,
        build_agent=lambda: synthetic_agent(toolsets),
        build_deps=_deps,
        charge_usage=ledger,
    )


def synthetic_spec(
    ledger: UsageLedger,
    *,
    tool_sources: ToolSourceDeclarations = (),
) -> AssistantSpec:
    """The synthetic assistant, as the runtime sees any assistant."""

    def build_graph(
        checkpointer: BaseCheckpointSaver[Any],
    ) -> CompiledStateGraph[Any, Any, Any, Any]:
        return synthetic_graph(checkpointer=checkpointer, ledger=ledger)

    async def build_turn_context(request: TurnContextRequest) -> TurnContext:
        return SyntheticTurnContext(
            site_id=request.site_id,
            user_id=request.user_id,
            db_session_factory=async_session_factory,
            cancel_event=request.cancel_event,
            memory_store=request.memory_store,
            phase_models=request.phase_models,
            phase_reasoning=request.phase_reasoning,
            tool_sources=request.tool_sources,
        )

    return AssistantSpec(
        assistant_id=SYNTHETIC_ASSISTANT_ID,
        build_graph=build_graph,
        build_initial_state=lambda start: TurnState(**start.state_kwargs()),
        build_turn_context=build_turn_context,
        build_mock_model=_mock_model,
        checkpoint_types=(TurnState,),
        memory_kinds=frozenset({"note"}),
        tool_sources=tool_sources,
        turn_epilogue=_epilogue,
    )


def _mock_model() -> Model:
    return synthetic_model().as_function_model()


def dump_chunk(chunk: BaseChunk) -> dict[str, Any]:
    return chunk.model_dump(by_alias=True, mode="json", exclude_none=True)


async def build_context(
    spec: AssistantSpec,
    *,
    user_id: UUID,
    cancel_event: asyncio.Event | None = None,
    tool_sources: Mapping[str, AbstractToolset[Any]] | None = None,
) -> TurnContext:
    return await spec.build_turn_context(
        TurnContextRequest(
            conversation=None,
            site_id=SYNTHETIC_SITE_ID,
            user_id=user_id,
            memory_store=None,
            cancel_event=cancel_event or asyncio.Event(),
            phase_models={},
            phase_reasoning={},
            tool_sources=tool_sources or {},
        ),
    )


@dataclass(frozen=True, kw_only=True)
class TurnRequest:
    """One turn's inputs for the driver below."""

    spec: AssistantSpec
    graph: CompiledStateGraph[Any, Any, Any, Any]
    writer: ChatWriter
    context: TurnContext
    conversation_id: UUID
    user_id: UUID
    prompt: str = ""
    is_resume: bool = False
    approval_responses: dict[str, ToolApprovalResponded] = field(default_factory=dict)


@dataclass
class TurnOutcome:
    """What one driven turn produced."""

    turn_message_id: UUID
    chunks: list[dict[str, Any]] = field(default_factory=list)
    start_event_id: int = 0
    cancelled: bool = False

    def types(self) -> list[str]:
        return [str(chunk["type"]) for chunk in self.chunks]

    def finish_reason(self) -> str:
        return "other" if self.cancelled else "stop"


def _turn_start(request: TurnRequest, start_event_id: int) -> TurnStart:
    return TurnStart(
        conversation_id=request.conversation_id,
        user_id=request.user_id,
        site_id=request.context.site_id,
        mode=SYNTHETIC_MODE,
        turn_message_id=request.writer.turn_id,
        turn_start_event_id=start_event_id - 1,
        is_resume=request.is_resume,
        user_message_id=None if request.is_resume else uuid4(),
        user_prompt="" if request.is_resume else request.prompt,
        approval_responses=request.approval_responses,
    )


async def _consume(request: TurnRequest, outcome: TurnOutcome) -> None:
    graph_input = turn_input(
        request.spec.build_initial_state(
            _turn_start(request, outcome.start_event_id),
        ),
    )
    config: dict[str, Any] = {
        "configurable": {"thread_id": str(request.conversation_id)},
    }
    async for _mode, payload in request.graph.astream(
        graph_input,
        config=config,
        context=request.context,
        stream_mode=["custom"],
    ):
        chunk = payload["chunk"]
        outcome.chunks.append(chunk)
        await request.writer.write(chunk)


async def drive_turn(request: TurnRequest) -> TurnOutcome:
    """Run one turn end to end, writing every chunk to the durable log.

    The framing is the wire contract: a ``start`` chunk opens the turn and a
    ``finish``/``done`` pair closes it, whatever the turn did in between.
    """
    outcome = TurnOutcome(turn_message_id=request.writer.turn_id)
    outcome.start_event_id = await request.writer.write(
        dump_chunk(StartChunk(message_id=str(request.writer.turn_id))),
    )
    await request.writer.write(
        dump_chunk(turn_status_event(label=PREPARING_LABEL)),
    )
    await _consume(request, outcome)
    outcome.cancelled = request.context.cancel_event.is_set()

    if outcome.cancelled:
        await request.writer.write(dump_chunk(turn_stopped_event()))
    if request.spec.turn_epilogue is not None:
        for chunk in await request.spec.turn_epilogue(request.conversation_id):
            await request.writer.write(chunk)
    await request.writer.write(
        dump_chunk(FinishChunk(finish_reason=outcome.finish_reason())),
    )
    await request.writer.write(dump_chunk(DoneChunk()))
    return outcome


@dataclass(frozen=True, kw_only=True)
class SyntheticRuntime:
    """One installed synthetic assistant and the thread its turns run on."""

    spec: AssistantSpec
    graph: CompiledStateGraph[Any, Any, Any, Any]
    ledger: UsageLedger
    conversation_id: UUID
    user_id: UUID

    async def run(
        self,
        prompt: str = "",
        *,
        is_resume: bool = False,
        cancel: asyncio.Event | None = None,
        approval_responses: dict[str, ToolApprovalResponded] | None = None,
    ) -> TurnOutcome:
        """Drive one turn, with its own message id and its own cancel event."""
        writer = ChatEventWriter(
            conversation_id=self.conversation_id,
            turn_id=uuid4(),
        )
        context = await build_context(
            self.spec,
            user_id=self.user_id,
            cancel_event=cancel,
        )
        return await drive_turn(
            TurnRequest(
                spec=self.spec,
                graph=self.graph,
                writer=writer,
                context=context,
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                prompt=prompt,
                is_resume=is_resume,
                approval_responses=approval_responses or {},
            ),
        )

    async def answer_approval(
        self,
        tool_call_id: str,
        *,
        approved: bool,
        reason: str = "",
    ) -> TurnOutcome:
        """Drive the turn that carries the user's answer to an approval card."""
        return await self.run(
            is_resume=True,
            approval_responses={
                tool_call_id: ToolApprovalResponded(
                    id=tool_call_id,
                    approved=approved,
                    reason=reason or None,
                ),
            },
        )

    def thread_config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": str(self.conversation_id)}}
