"""A turn graph for an assistant that is one agent.

The agent answers the user directly: its text and its tool calls stream to the
client as the turn's message, and the turn's tokens and cost land on the
state. A tool the agent must ask about parks on the state until the user
answers, and a durable tool parks there until the worker answers. The graph
names no phase, no role and no other agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic_ai import Agent, AgentRunResultEvent
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolResultEvent,
    ModelMessage,
    PartStartEvent,
)
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage

from assistant_core.capabilities.repetition_guard import RepetitionGuard
from assistant_core.conversation.vercel_adapter import (
    DeferredToolHint,
    PhaseStreamEmitter,
)
from assistant_core.cost import cost_for_run
from assistant_core.graph.approvals import (
    approval_results,
    deferred_hint,
    durable_hints,
    parked_durable_call,
    pending_approval,
    resume_history,
)
from assistant_core.graph.durable import durable_tool_results
from assistant_core.graph.emit import emit_chunk, emit_turn_usage
from assistant_core.graph.runtime import GuardedDeps, TurnContext
from assistant_core.graph.stream_events import turn_status_event
from assistant_core.graph.thread_history import dump_thread_history, thread_history
from assistant_core.graph.turn_agent import TurnAgentFactory
from assistant_core.graph.turn_message import write_turn_message
from assistant_core.graph.turn_state import (
    DurableCall,
    DurableDeferral,
    PendingApproval,
    PendingDurableCall,
    TurnState,
)

_AGENT_NODE = "agent"
_FINALIZE_NODE = "finalize_turn"

# Records one turn's tokens and cost against the user's budget.
type UsageCharger = Callable[[UUID, int, Decimal], Awaitable[None]]

type _RunEvent = AgentStreamEvent | AgentRunResultEvent[str | DeferredToolRequests]


@dataclass
class _RunCapture:
    """The accounting facts one agent run produces."""

    usage: RunUsage = field(default_factory=RunUsage)
    model_name: str | None = None
    provider_name: str | None = None
    provider_url: str | None = None
    pending_approval: PendingApproval | None = None
    pending_durable_call: PendingDurableCall | None = None
    messages: list[ModelMessage] = field(default_factory=list)

    def cost_usd(self) -> Decimal:
        return cost_for_run(
            usage=self.usage,
            model_name=self.model_name,
            provider_name=self.provider_name,
            provider_url=self.provider_url,
        )


@dataclass(frozen=True)
class _AgentTurn:
    """What the run starts from: a new prompt, or an answered approval."""

    prompt: str | None = None
    history: list[ModelMessage] | None = None
    results: DeferredToolResults | None = None
    hints: tuple[DeferredToolHint, ...] = ()


def _turn_for(state: TurnState) -> _AgentTurn:
    """A turn that answers the parked call, else one that answers the user.

    A message that answers nothing supersedes the card: the deferred call is
    never made, so the turn is a fresh one over the thread's own messages.
    """
    durable = state.answered_durable_call
    if durable is not None:
        return _AgentTurn(
            history=resume_history(durable),
            results=durable_tool_results(durable, state.durable_answers),
            hints=tuple(durable_hints(durable)),
        )
    approval = state.pending_approval
    if approval is not None:
        results = approval_results(approval, state.approval_responses)
        if results is not None:
            return _AgentTurn(
                history=resume_history(approval),
                results=results,
                hints=(deferred_hint(approval),),
            )
    return _AgentTurn(
        prompt=state.user_prompt,
        history=thread_history(state.thread_messages_json),
    )


def _absorb(
    event: AgentRunResultEvent[str | DeferredToolRequests],
    capture: _RunCapture,
    deferrals: dict[str, DurableDeferral],
) -> None:
    result = event.result
    response = result.response
    capture.model_name = response.model_name
    capture.provider_name = response.provider_name
    capture.provider_url = response.provider_url
    capture.messages = list(result.all_messages())
    output = result.output
    if not isinstance(output, DeferredToolRequests):
        return
    # One agent is one role, so a parked call names the only node that can
    # raise one. A durable call outranks an approval: its task already runs.
    deferred = [c for c in output.calls if c.tool_call_id in deferrals]
    if deferred:
        capture.pending_durable_call = parked_durable_call(
            call=deferred[0],
            phase=_AGENT_NODE,
            messages=capture.messages,
            durable_calls=[
                DurableCall(
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    args=call.args_as_dict(),
                    task_id=deferrals[call.tool_call_id].task_id,
                    durable_tool_name=deferrals[call.tool_call_id].tool_name,
                )
                for call in deferred
            ],
        )
        return
    capture.pending_approval = pending_approval(
        output=output,
        phase=_AGENT_NODE,
        messages=capture.messages,
    )


def _advanced_history(state: TurnState, capture: _RunCapture) -> str:
    """The thread's messages after this turn.

    A run that produced no result kept none, so the thread stays where the
    last settled turn left it.
    """
    if not capture.messages:
        return state.thread_messages_json
    return dump_thread_history(capture.messages)


async def _stream_answer[DepsT: GuardedDeps](
    *,
    agent: Agent[DepsT, str],
    deps: DepsT,
    turn: _AgentTurn,
    cancel: asyncio.Event,
    capture: _RunCapture,
    writer: Any,
) -> None:
    """Run the agent for one turn, writing every chunk it produces.

    A cancelled turn ends before the next part the model starts, so it spends
    no further model call and every call the run already made still reports
    its outcome. A run the repetition guard stopped ends the same way, once
    the refusal has reached the client.
    """
    emitter = PhaseStreamEmitter(
        message_id=str(uuid4()),
        deferred_hints=list(turn.hints),
    )
    guard = deps.tool_repetition_guard

    async def _events() -> AsyncGenerator[_RunEvent]:
        events: AsyncIterator[_RunEvent]
        event: _RunEvent
        async with agent.run_stream_events(
            turn.prompt,
            deps=deps,
            message_history=turn.history,
            deferred_tool_results=turn.results,
            output_type=[str, DeferredToolRequests],
            capabilities=[RepetitionGuard(guard=guard)],
            usage=capture.usage,
        ) as events:
            async for event in events:
                if cancel.is_set() and isinstance(event, PartStartEvent):
                    return
                if isinstance(event, AgentRunResultEvent):
                    _absorb(event, capture, deps.durable_deferrals)
                yield event
                if (
                    isinstance(event, FunctionToolResultEvent)
                    and event.tool_call_id == guard.stopped_call_id
                ):
                    return

    async for chunk in emitter.chunks(_events()):
        emit_chunk(writer, chunk)


def single_agent_graph[
    StateT: TurnState,
    ContextT: TurnContext,
    DepsT: GuardedDeps,
](
    *,
    checkpointer: BaseCheckpointSaver[Any],
    state_type: type[StateT],
    context_type: type[ContextT],
    build_agent: TurnAgentFactory[Agent[DepsT, str]],
    build_deps: Callable[[StateT, ContextT], DepsT],
    charge_usage: UsageCharger,
) -> CompiledStateGraph[StateT, ContextT, StateT, StateT]:
    """Compile the turn graph for a one-agent assistant.

    The finalize step runs after the agent's, because the message row is
    reduced from chunks the log only holds once the agent's step has ended.
    """

    async def agent_node(
        state: StateT,
        runtime: Runtime[ContextT],
    ) -> dict[str, Any]:
        writer = get_stream_writer()
        context = runtime.context
        capture = _RunCapture()
        emit_chunk(writer, turn_status_event(label="Thinking...", waiting_on_llm=True))
        await _stream_answer(
            agent=build_agent(),
            deps=build_deps(state, context),
            turn=_turn_for(state),
            cancel=context.cancel_event,
            capture=capture,
            writer=writer,
        )
        tokens = capture.usage.total_tokens
        cost = capture.cost_usd()
        await charge_usage(state.user_id, tokens, cost)
        total_tokens = state.turn_total_tokens + tokens
        total_cost = state.turn_total_cost_usd + cost
        emit_turn_usage(writer, total_tokens, str(total_cost))
        return {
            "turn_total_tokens": total_tokens,
            "turn_total_cost_usd": total_cost,
            "pending_approval": capture.pending_approval,
            "pending_durable_call": capture.pending_durable_call,
            "thread_messages_json": _advanced_history(state, capture),
        }

    async def finalize_node(state: StateT, runtime: Runtime[ContextT]) -> None:
        await write_turn_message(context=runtime.context, state=state)

    graph: StateGraph[StateT, ContextT, StateT, StateT] = StateGraph(
        state_type,
        context_schema=context_type,
    )
    graph.add_node(_AGENT_NODE, agent_node)
    graph.add_node(_FINALIZE_NODE, finalize_node)
    graph.add_edge(START, _AGENT_NODE)
    graph.add_edge(_AGENT_NODE, _FINALIZE_NODE)
    graph.add_edge(_FINALIZE_NODE, END)
    return graph.compile(checkpointer=checkpointer)


__all__ = ["UsageCharger", "single_agent_graph"]
