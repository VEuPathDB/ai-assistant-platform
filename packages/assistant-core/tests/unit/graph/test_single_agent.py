"""The stock single-agent turn graph, driven by a scripted model.

One agent answers the turn. The helper owns the chunk emission, the token and
cost accounting, and the cancel check; it names no assistant.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.ui.vercel_ai.request_types import ToolApprovalResponded

from assistant_core.graph import turn_message
from assistant_core.graph.runtime import AssistantDeps, TurnContext
from assistant_core.graph.single_agent import single_agent_graph
from assistant_core.graph.turn_state import TurnState
from assistant_core.platform.db import async_session_factory
from assistant_core.spec import TurnStart, turn_input

type ProbeAgent = Agent[AssistantDeps, str]
type ProbeTool = Callable[..., Any] | Tool[AssistantDeps]


class _Charges:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, Decimal]] = []

    async def __call__(self, user_id: UUID, tokens: int, cost_usd: Decimal) -> None:
        self.calls.append((user_id, tokens, cost_usd))


def _deps(state: TurnState, context: TurnContext) -> AssistantDeps:
    return AssistantDeps(
        site_id=context.site_id,
        user_id=context.user_id,
        conversation_id=state.conversation_id,
        cancel_event=context.cancel_event,
    )


def _text_model(text: str) -> FunctionModel:
    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(content=text)])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield text

    return FunctionModel(_respond, stream_function=_stream, model_name="test:text")


def _has_tool_call(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ToolCallPart)
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
    )


def _tool_then_text_model(tool_name: str, text: str) -> FunctionModel:
    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _has_tool_call(messages):
            return ModelResponse(parts=[TextPart(content=text)])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool_name, args={}, tool_call_id="call-1")],
        )

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        if _has_tool_call(messages):
            yield text
            return
        yield {0: DeltaToolCall(name=tool_name, json_args="{}", tool_call_id="call-1")}

    return FunctionModel(_respond, stream_function=_stream, model_name="test:tool")


def _agent(model: FunctionModel, tools: list[ProbeTool]) -> ProbeAgent:
    return Agent(
        model,
        output_type=str,
        deps_type=AssistantDeps,
        instructions="Answer.",
        tools=list(tools),
        name="probe",
    )


def _context(cancel: asyncio.Event) -> TurnContext:
    return TurnContext(
        site_id="plasmodb",
        user_id=uuid4(),
        db_session_factory=async_session_factory,
        cancel_event=cancel,
    )


async def _run(
    model: FunctionModel,
    *,
    tools: list[ProbeTool] | None = None,
    cancel: asyncio.Event | None = None,
    charges: _Charges | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context = _context(cancel or asyncio.Event())
    graph = single_agent_graph(
        checkpointer=InMemorySaver(),
        state_type=TurnState,
        context_type=TurnContext,
        build_agent=lambda: _agent(model, tools or []),
        build_deps=_deps,
        charge_usage=charges or _Charges(),
    )
    conversation_id = uuid4()
    state = TurnState(
        conversation_id=conversation_id,
        user_id=context.user_id,
        site_id="plasmodb",
        mode="strategy",
        user_prompt="which sites",
    )
    config: dict[str, Any] = {"configurable": {"thread_id": str(conversation_id)}}
    chunks: list[dict[str, Any]] = []
    async for _mode, payload in graph.astream(
        turn_input(state),
        config=config,
        context=context,
        stream_mode=["custom"],
    ):
        chunks.append(payload["chunk"])
    snapshot = await graph.aget_state(config)
    return chunks, snapshot.values


@pytest.fixture(autouse=True)
def _no_durable_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """The turn-message write reads the durable log; this suite has no database."""

    async def _empty(
        conversation_id: UUID,
        after: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        del conversation_id
        return after, []

    monkeypatch.setattr(turn_message, "fetch_chunks_after", _empty)


def test_the_graph_is_the_agent_node_and_the_runtime_s_finalize() -> None:
    graph = single_agent_graph(
        checkpointer=InMemorySaver(),
        state_type=TurnState,
        context_type=TurnContext,
        build_agent=lambda: _agent(_text_model("hi"), []),
        build_deps=_deps,
        charge_usage=_Charges(),
    )

    assert set(graph.get_graph().nodes) >= {"agent", "finalize_turn"}


async def test_the_agent_s_answer_streams_as_text_chunks() -> None:
    chunks, _values = await _run(_text_model("PlasmoDB and ToxoDB."))

    assert [c["type"] for c in chunks] == [
        "data-turn-status",
        "start-step",
        "text-start",
        "text-delta",
        "text-end",
        "message-metadata",
        "finish-step",
        "data-turn-usage",
    ]
    assert chunks[3]["delta"] == "PlasmoDB and ToxoDB."


async def test_a_tool_call_streams_its_input_and_output() -> None:
    async def ping() -> str:
        """Answer with pong."""
        return "pong"

    chunks, _values = await _run(
        _tool_then_text_model("ping", "Done."),
        tools=[ping],
    )

    types = [c["type"] for c in chunks]
    assert "tool-input-available" in types
    assert "tool-output-available" in types
    output = next(c for c in chunks if c["type"] == "tool-output-available")
    assert output["output"] == "pong"
    assert types[-1] == "data-turn-usage"


async def test_the_turn_s_tokens_and_cost_land_on_the_state() -> None:
    charges = _Charges()

    chunks, values = await _run(_text_model("hello"), charges=charges)

    assert values["turn_total_tokens"] > 0
    assert values["turn_total_cost_usd"] == Decimal(0)
    usage_chunk = next(c for c in chunks if c["type"] == "data-turn-usage")
    assert usage_chunk["data"]["totalTokens"] == values["turn_total_tokens"]
    assert charges.calls == [
        (values["user_id"], values["turn_total_tokens"], Decimal(0)),
    ]


async def test_a_cancelled_turn_leaves_the_thread_where_it_was() -> None:
    """A run that reports no result keeps nothing, and the turn before it is
    still the history the next turn reads."""
    seen = _Seen()
    cancel = asyncio.Event()

    async def stop_now() -> str:
        """Stop the turn that is running."""
        cancel.set()
        return "stopping"

    thread = _Thread(_recall_or_stop_model(seen), tools=[stop_now], cancel=cancel)

    await thread.turn(_FIRST_PROMPT)
    await thread.turn(_STOP_PROMPT)
    chunks = await thread.turn(_SECOND_PROMPT)

    last = seen.runs[-1]
    assert _rendered(last) == f"{_FIRST_PROMPT} Noted. {_SECOND_PROMPT}"
    assert _calls(last) == []
    assert _text(chunks) == f"The code word is {_CODE_WORD}."


async def test_a_cancelled_turn_makes_no_further_model_call_and_finalizes() -> None:
    """The tool sets the cancel; the answer the next model call would have
    produced is never streamed, and the turn still accounts for what it used."""
    cancel = asyncio.Event()

    async def stop_now() -> str:
        """Stop the turn."""
        cancel.set()
        return "stopped"

    chunks, values = await _run(
        _tool_then_text_model("stop_now", "never streamed"),
        tools=[stop_now],
        cancel=cancel,
    )

    types = [c["type"] for c in chunks]
    assert "text-delta" not in types
    assert types[-1] == "data-turn-usage"
    assert values["turn_total_tokens"] > 0


@dataclass
class _Seen:
    """Every message list the model was asked to answer, in order."""

    runs: list[list[ModelMessage]] = field(default_factory=list)


def _rendered(messages: list[ModelMessage]) -> str:
    return " ".join(
        str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, UserPromptPart | TextPart)
    )


def _calls(messages: list[ModelMessage]) -> list[ToolCallPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]


def _returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def _text(chunks: list[dict[str, Any]]) -> str:
    return "".join(str(c["delta"]) for c in chunks if c["type"] == "text-delta")


_CODE_WORD = "kinase"
_FIRST_PROMPT = f"Remember that the code word is {_CODE_WORD}."
_SECOND_PROMPT = "What is the code word?"


def _recall_model(seen: _Seen) -> FunctionModel:
    """The second answer exists only when the first turn reaches the model."""

    def _answer(messages: list[ModelMessage]) -> str:
        seen.runs.append(list(messages))
        prior = messages[:-1]
        if not prior:
            return "Noted."
        if _CODE_WORD in _rendered(prior):
            return f"The code word is {_CODE_WORD}."
        return "I do not know the code word."

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        return ModelResponse(parts=[TextPart(content=_answer(messages))])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        yield _answer(messages)

    return FunctionModel(_respond, stream_function=_stream, model_name="test:recall")


_WIPE_TOOL = "wipe"
_WIPE_CALL_ID = "call-wipe"
_WIPE_PROMPT = "please wipe the workspace"


async def wipe() -> str:
    """Delete the workspace."""
    return "wiped"


def _approval_model(seen: _Seen) -> FunctionModel:
    """Calls the approval-gated tool for the wipe prompt, else answers text."""

    def _part(messages: list[ModelMessage]) -> ToolCallPart | TextPart:
        seen.runs.append(list(messages))
        if _has_tool_call(messages):
            return TextPart(content="Done.")
        if _WIPE_PROMPT in _rendered(messages[-1:]):
            return ToolCallPart(
                tool_name=_WIPE_TOOL,
                args={},
                tool_call_id=_WIPE_CALL_ID,
            )
        return TextPart(content="Nothing to do.")

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        return ModelResponse(parts=[_part(messages)])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        part = _part(messages)
        if isinstance(part, TextPart):
            yield part.content
            return
        yield {
            0: DeltaToolCall(
                name=part.tool_name,
                json_args="{}",
                tool_call_id=part.tool_call_id,
            ),
        }

    return FunctionModel(_respond, stream_function=_stream, model_name="test:approval")


_STOP_PROMPT = "stop this turn"
_STOP_TOOL = "stop_now"


def _recall_or_stop_model(seen: _Seen) -> FunctionModel:
    """Answers from the thread, unless the prompt asks the tool to stop it."""

    def _part(messages: list[ModelMessage]) -> ToolCallPart | TextPart:
        seen.runs.append(list(messages))
        if _has_tool_call(messages):
            return TextPart(content="Stopped.")
        if _STOP_PROMPT in _rendered(messages[-1:]):
            return ToolCallPart(
                tool_name=_STOP_TOOL,
                args={},
                tool_call_id="call-stop",
            )
        prior = messages[:-1]
        if not prior:
            return TextPart(content="Noted.")
        if _CODE_WORD in _rendered(prior):
            return TextPart(content=f"The code word is {_CODE_WORD}.")
        return TextPart(content="I do not know the code word.")

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        return ModelResponse(parts=[_part(messages)])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        part = _part(messages)
        if isinstance(part, TextPart):
            yield part.content
            return
        yield {
            0: DeltaToolCall(
                name=part.tool_name,
                json_args="{}",
                tool_call_id=part.tool_call_id,
            ),
        }

    return FunctionModel(_respond, stream_function=_stream, model_name="test:stop")


class _Thread:
    """One conversation, driven a turn at a time through one compiled graph."""

    def __init__(
        self,
        model: FunctionModel,
        *,
        tools: list[ProbeTool] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> None:
        self.context = _context(cancel or asyncio.Event())
        self.graph = single_agent_graph(
            checkpointer=InMemorySaver(),
            state_type=TurnState,
            context_type=TurnContext,
            build_agent=lambda: _agent(model, tools or []),
            build_deps=_deps,
            charge_usage=_Charges(),
        )
        self.conversation_id = uuid4()
        self.config: dict[str, Any] = {
            "configurable": {"thread_id": str(self.conversation_id)},
        }

    async def turn(
        self,
        prompt: str = "",
        *,
        approvals: dict[str, ToolApprovalResponded] | None = None,
    ) -> list[dict[str, Any]]:
        # Every turn of a thread is driven under a cancel of its own.
        self.context.cancel_event.clear()
        start = TurnStart(
            conversation_id=self.conversation_id,
            user_id=self.context.user_id,
            site_id=self.context.site_id,
            mode="chat",
            turn_message_id=uuid4(),
            turn_start_event_id=0,
            is_resume=approvals is not None,
            user_message_id=uuid4(),
            user_prompt=prompt,
            approval_responses=approvals or {},
        )
        chunks: list[dict[str, Any]] = []
        async for _mode, payload in self.graph.astream(
            turn_input(TurnState(**start.state_kwargs())),
            config=self.config,
            context=self.context,
            stream_mode=["custom"],
        ):
            chunks.append(payload["chunk"])
        return chunks


async def test_the_second_turn_answers_from_the_first_turn_s_messages() -> None:
    """The thread's own transcript reaches the model, so a follow-up resolves."""
    seen = _Seen()
    thread = _Thread(_recall_model(seen))

    await thread.turn(_FIRST_PROMPT)
    chunks = await thread.turn(_SECOND_PROMPT)

    second = seen.runs[1]
    assert [type(message) for message in second] == [
        ModelRequest,
        ModelResponse,
        ModelRequest,
    ]
    assert _rendered(second) == f"{_FIRST_PROMPT} Noted. {_SECOND_PROMPT}"
    assert _text(chunks) == f"The code word is {_CODE_WORD}."


async def test_a_superseded_approval_leaves_no_unanswered_call_in_the_history() -> None:
    """pydantic-ai refuses a new prompt over a history that holds an unprocessed
    call, so the thread carries whole exchanges and stops at the last answer."""
    seen = _Seen()
    thread = _Thread(
        _approval_model(seen),
        tools=[Tool(wipe, requires_approval=True)],
    )

    await thread.turn("what else can you do")
    await thread.turn(_WIPE_PROMPT)
    await thread.turn("and now")

    last = seen.runs[-1]
    assert [type(message) for message in last] == [
        ModelRequest,
        ModelResponse,
        ModelRequest,
    ]
    assert _rendered(last) == "what else can you do Nothing to do. and now"
    assert _calls(last) == []


async def test_an_answered_call_and_its_result_reach_the_next_turn() -> None:
    """A settled approval advances the thread, paired with the call it answers."""
    seen = _Seen()
    thread = _Thread(
        _approval_model(seen),
        tools=[Tool(wipe, requires_approval=True)],
    )

    await thread.turn(_WIPE_PROMPT)
    await thread.turn(
        approvals={
            _WIPE_CALL_ID: ToolApprovalResponded(id=_WIPE_CALL_ID, approved=True),
        },
    )
    await thread.turn("what did you do")

    last = seen.runs[-1]
    assert [call.tool_call_id for call in _calls(last)] == [_WIPE_CALL_ID]
    assert [ret.tool_call_id for ret in _returns(last)] == [_WIPE_CALL_ID]
    assert _WIPE_PROMPT in _rendered(last)


async def test_a_cancelled_turn_still_reports_the_tool_that_already_ran() -> None:
    """A tool the cancel interrupted has already produced its result, so the
    stream carries it rather than leaving the call without an outcome."""
    cancel = asyncio.Event()

    async def stop_now() -> str:
        """Stop the turn."""
        cancel.set()
        return "stopped"

    chunks, _values = await _run(
        _tool_then_text_model("stop_now", "never streamed"),
        tools=[stop_now],
        cancel=cancel,
    )

    outputs = [c for c in chunks if c["type"] == "tool-output-available"]
    assert [c["output"] for c in outputs] == ["stopped"]
    assert outputs[0]["toolCallId"] == "call-1"
