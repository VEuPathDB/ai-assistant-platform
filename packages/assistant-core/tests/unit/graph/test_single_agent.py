"""The stock single-agent turn graph, driven by a scripted model.

One agent answers the turn. The helper owns the chunk emission, the token and
cost accounting, and the cancel check; it names no assistant.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, Tool
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ContentFilterError
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.output import OutputContext
from pydantic_ai.tools import RunContext
from pydantic_ai.ui.vercel_ai.request_types import FileUIPart, ToolApprovalResponded
from pydantic_ai.usage import UsageLimits

from assistant_core.conversation.vercel_adapter import DECLINED_BY_THE_MODEL
from assistant_core.graph import turn_message
from assistant_core.graph.runtime import AssistantDeps, TurnContext
from assistant_core.graph.single_agent import (
    SingleAgent,
    TypedReply,
    single_agent_graph,
)
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
        agent=SingleAgent(
            build_agent=lambda: _agent(model, tools or []),
            build_deps=_deps,
        ),
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
        agent=SingleAgent(
            build_agent=lambda: _agent(_text_model("hi"), []),
            build_deps=_deps,
        ),
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
        agent: Callable[[], ProbeAgent] | None = None,
        usage_limits: UsageLimits | None = None,
        reply: TypedReply[AssistantDeps, Any] | None = None,
    ) -> None:
        self.context = _context(cancel or asyncio.Event())
        self.charges = _Charges()
        self.graph = single_agent_graph(
            checkpointer=InMemorySaver(),
            state_type=TurnState,
            context_type=TurnContext,
            agent=SingleAgent(
                build_agent=agent or (lambda: _agent(model, tools or [])),
                build_deps=_deps,
                usage_limits=usage_limits,
                reply=reply,
            ),
            charge_usage=self.charges,
        )
        self.conversation_id = uuid4()
        self.config: dict[str, Any] = {
            "configurable": {"thread_id": str(self.conversation_id)},
        }
        self.prompt_ids: list[UUID] = []

    async def turn(
        self,
        prompt: str = "",
        *,
        approvals: dict[str, ToolApprovalResponded] | None = None,
        files: tuple[FileUIPart, ...] = (),
    ) -> list[dict[str, Any]]:
        # Every turn of a thread is driven under a cancel of its own.
        self.context.cancel_event.clear()
        self.prompt_ids.append(uuid4())
        start = TurnStart(
            conversation_id=self.conversation_id,
            user_id=self.context.user_id,
            site_id=self.context.site_id,
            mode="chat",
            turn_message_id=uuid4(),
            turn_start_event_id=0,
            is_resume=approvals is not None,
            user_message_id=self.prompt_ids[-1],
            user_prompt=prompt,
            user_files=files,
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

    async def values(self) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self.config)
        return snapshot.values


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


_PNG = b"\x89PNG\r\n\x1a\n-probe-image"
_IMAGE = FileUIPart(
    media_type="image/png",
    filename="blot.png",
    url="data:image/png;base64,iVBORw0KGgotcHJvYmUtaW1hZ2U=",
)


def _user_contents(messages: list[ModelMessage]) -> list[object]:
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]


def _is_the_image(item: object) -> bool:
    return (
        isinstance(item, BinaryContent)
        and item.data == _PNG
        and item.media_type == "image/png"
    )


async def test_an_attached_image_reaches_the_model_as_bytes_before_the_text() -> None:
    seen = _Seen()
    thread = _Thread(_recall_model(seen))

    await thread.turn("What does this blot show?", files=(_IMAGE,))

    [content] = _user_contents(seen.runs[0])
    assert isinstance(content, list)
    assert len(content) == 2
    assert _is_the_image(content[0])
    assert content[1] == "What does this blot show?"


async def test_a_message_without_a_file_reaches_the_model_as_a_string() -> None:
    seen = _Seen()
    thread = _Thread(_recall_model(seen))

    await thread.turn(_FIRST_PROMPT)

    assert _user_contents(seen.runs[0]) == [_FIRST_PROMPT]


async def test_an_image_from_an_earlier_turn_stays_in_the_thread_history() -> None:
    seen = _Seen()
    thread = _Thread(_recall_model(seen))

    await thread.turn("What does this blot show?", files=(_IMAGE,))
    await thread.turn(_SECOND_PROMPT)

    first, second = _user_contents(seen.runs[1])
    assert isinstance(first, list)
    assert _is_the_image(first[0])
    assert first[1] == "What does this blot show?"
    assert second == _SECOND_PROMPT


_DECLINED_PROMPT = "Describe the virulence factors of this strain."


def _declining_model(seen: _Seen) -> FunctionModel:
    def _answer(messages: list[ModelMessage]) -> str:
        seen.runs.append(list(messages))
        if _DECLINED_PROMPT in _rendered(messages[-1:]):
            msg = "Content filter triggered. Finish reason: 'refusal'"
            raise ContentFilterError(msg)
        if _CODE_WORD in _rendered(messages[:-1]):
            return f"The code word is {_CODE_WORD}."
        return "Noted."

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        return ModelResponse(parts=[TextPart(content=_answer(messages))])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        yield _answer(messages)

    return FunctionModel(_respond, stream_function=_stream, model_name="test:decline")


async def test_a_declined_turn_withdraws_its_prompt() -> None:
    thread = _Thread(_declining_model(_Seen()))

    await thread.turn(_FIRST_PROMPT)
    chunks = await thread.turn(_DECLINED_PROMPT)

    assert [c for c in chunks if c["type"] in {"error", "data-turn-withdrawn"}] == [
        {
            "type": "data-turn-withdrawn",
            "data": {
                "errorText": DECLINED_BY_THE_MODEL,
                "messageId": str(thread.prompt_ids[-1]),
            },
        },
        {"type": "error", "errorText": DECLINED_BY_THE_MODEL},
    ]


async def test_the_turn_after_a_declined_one_never_sends_its_prompt() -> None:
    seen = _Seen()
    thread = _Thread(_declining_model(seen))

    await thread.turn(_FIRST_PROMPT)
    await thread.turn(_DECLINED_PROMPT)
    chunks = await thread.turn(_SECOND_PROMPT)

    assert _rendered(seen.runs[-1]) == f"{_FIRST_PROMPT} Noted. {_SECOND_PROMPT}"
    assert _text(chunks) == f"The code word is {_CODE_WORD}."


def _declines_after_the_tool(seen: _Seen) -> FunctionModel:
    def _part(messages: list[ModelMessage]) -> ToolCallPart | TextPart:
        seen.runs.append(list(messages))
        if _returns(messages):
            msg = "Content filter triggered. Finish reason: 'refusal'"
            raise ContentFilterError(msg)
        if _WIPE_PROMPT in _rendered(messages[-1:]):
            return ToolCallPart(
                tool_name=_WIPE_TOOL, args={}, tool_call_id=_WIPE_CALL_ID
            )
        return TextPart(content="Noted.")

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
                name=part.tool_name, json_args="{}", tool_call_id=part.tool_call_id
            ),
        }

    return FunctionModel(_respond, stream_function=_stream, model_name="test:resume")


async def test_a_resumed_turn_the_model_declined_withdraws_its_run_alone() -> None:
    seen = _Seen()
    thread = _Thread(
        _declines_after_the_tool(seen),
        tools=[Tool(wipe, requires_approval=True)],
    )

    await thread.turn(_FIRST_PROMPT)
    await thread.turn(_WIPE_PROMPT)
    declined = await thread.turn(
        approvals={
            _WIPE_CALL_ID: ToolApprovalResponded(id=_WIPE_CALL_ID, approved=True),
        },
    )
    await thread.turn("and now")

    assert [c for c in declined if c["type"] == "data-turn-withdrawn"] == [
        {"type": "data-turn-withdrawn", "data": {"errorText": DECLINED_BY_THE_MODEL}},
    ]
    assert _rendered(seen.runs[-1]) == f"{_FIRST_PROMPT} Noted. and now"


_REFUSED_PROSE = "REFUSED-PROSE"
_TYPED_PROSE = "two [x]"
_LOOP_PROMPT = "keep reading pages"


class _Reply(BaseModel):
    prose: str


_RENDERED = TypedReply[AssistantDeps, _Reply](
    output_type=_Reply,
    text=lambda reply, deps: reply.prose.replace("[x]", "facts"),
)


def _reply_model(seen: _Seen, proses: list[str]) -> FunctionModel:
    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        seen.runs.append(list(messages))
        prose = proses[min(len(seen.runs), len(proses)) - 1]
        yield {
            0: DeltaToolCall(
                name=info.output_tools[0].name,
                json_args=json.dumps({"prose": prose}),
                tool_call_id=f"reply-{len(seen.runs)}",
            ),
        }

    return FunctionModel(stream_function=_stream, model_name="test:reply")


def _capable_agent(
    model: FunctionModel,
    capabilities: list[Hooks[AssistantDeps]],
    tools: list[ProbeTool] | None = None,
) -> ProbeAgent:
    return Agent(
        model,
        deps_type=AssistantDeps,
        instructions="Answer.",
        tools=list(tools or []),
        capabilities=list(capabilities),
        name="probe",
    )


def _refuse(prose: str, refused: list[str]) -> Hooks[AssistantDeps]:
    hooks = Hooks[AssistantDeps]()

    @hooks.on.after_output_validate
    async def hold_the_reply(
        ctx: RunContext[AssistantDeps],
        /,
        *,
        output_context: OutputContext,
        output: _Reply,
    ) -> _Reply:
        del ctx, output_context
        if output.prose == prose:
            refused.append(output.prose)
            msg = "Write the reply again."
            raise ModelRetry(msg)
        return output

    return hooks


async def test_a_typed_reply_is_written_as_the_turns_text() -> None:
    model = _reply_model(_Seen(), [_TYPED_PROSE])
    thread = _Thread(model, agent=lambda: _capable_agent(model, []), reply=_RENDERED)

    chunks = await thread.turn("how many facts")

    assert _text(chunks) == "two facts"
    assert [c["type"] for c in chunks if c["type"].startswith("tool-")] == []


async def test_a_refused_reply_never_reaches_the_client() -> None:
    seen = _Seen()
    refused: list[str] = []
    model = _reply_model(seen, [_REFUSED_PROSE, _TYPED_PROSE])
    thread = _Thread(
        model,
        agent=lambda: _capable_agent(model, [_refuse(_REFUSED_PROSE, refused)]),
        reply=_RENDERED,
    )

    chunks = await thread.turn("how many facts")

    assert refused == [_REFUSED_PROSE]
    assert len(seen.runs) == 2
    assert _REFUSED_PROSE not in json.dumps(chunks)
    assert _text(chunks) == "two facts"


async def test_a_typed_reply_reaches_the_next_turn() -> None:
    seen = _Seen()
    model = _reply_model(seen, [_TYPED_PROSE])
    thread = _Thread(model, agent=lambda: _capable_agent(model, []), reply=_RENDERED)

    await thread.turn(_FIRST_PROMPT)
    await thread.turn(_SECOND_PROMPT)

    second = seen.runs[1]
    assert _user_contents(second) == [_FIRST_PROMPT, _SECOND_PROMPT]
    assert [call.tool_call_id for call in _calls(second)] == ["reply-1"]
    assert [ret.tool_call_id for ret in _returns(second)] == ["reply-1"]


def _looping_model(seen: _Seen) -> FunctionModel:
    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        seen.runs.append(list(messages))
        if _user_contents(messages)[-1] != _LOOP_PROMPT:
            yield "Noted."
            return
        page = len(_calls(messages)) + 1
        yield {
            0: DeltaToolCall(
                name="read_page",
                json_args=json.dumps({"page": page}),
                tool_call_id=f"page-{page}",
            ),
        }

    return FunctionModel(stream_function=_stream, model_name="test:loop")


async def read_page(page: int) -> str:
    """Read one page."""
    return f"page {page}"


def _request_tokens(spent: list[int]) -> Hooks[AssistantDeps]:
    hooks = Hooks[AssistantDeps]()

    @hooks.on.after_model_request
    async def count_tokens(
        ctx: RunContext[AssistantDeps],
        /,
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        del ctx, request_context
        spent.append(response.usage.total_tokens)
        return response

    return hooks


async def test_a_turn_stops_at_its_usage_limit() -> None:
    seen = _Seen()
    spent: list[int] = []
    model = _looping_model(seen)
    thread = _Thread(
        model,
        agent=lambda: _capable_agent(model, [_request_tokens(spent)], [read_page]),
        usage_limits=UsageLimits(request_limit=3),
    )
    await thread.turn(_FIRST_PROMPT)
    before = (await thread.values())["thread_messages_json"]
    seen.runs.clear()
    spent.clear()

    chunks = await thread.turn(_LOOP_PROMPT)

    errors = [c for c in chunks if c["type"] == "error"]
    assert len(errors) == 1
    assert "request_limit of 3" in errors[0]["errorText"]
    assert [c["type"] for c in chunks][-3:] == [
        "error",
        "finish-step",
        "data-turn-usage",
    ]
    assert [c for c in chunks if c["type"] == "data-turn-failed"] == []
    assert len(seen.runs) == 3
    assert (await thread.values())["thread_messages_json"] == before
    assert len(spent) == 3
    assert thread.charges.calls[-1][1] == sum(spent)


_PREAMBLE = "PREAMBLE-PROSE"


def _talking_reply_model(seen: _Seen) -> FunctionModel:
    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        seen.runs.append(list(messages))
        prose = _REFUSED_PROSE if len(seen.runs) == 1 else _TYPED_PROSE
        yield f"{_PREAMBLE} {len(seen.runs)}"
        yield {
            1: DeltaToolCall(
                name=info.output_tools[0].name,
                json_args=json.dumps({"prose": prose}),
                tool_call_id=f"reply-{len(seen.runs)}",
            ),
        }

    return FunctionModel(stream_function=_stream, model_name="test:talking")


async def test_a_typed_reply_turn_shows_only_the_accepted_reply() -> None:
    seen = _Seen()
    refused: list[str] = []
    model = _talking_reply_model(seen)
    thread = _Thread(
        model,
        agent=lambda: _capable_agent(model, [_refuse(_REFUSED_PROSE, refused)]),
        reply=_RENDERED,
    )

    chunks = await thread.turn("how many facts")

    written = json.dumps(chunks)
    assert refused == [_REFUSED_PROSE]
    assert len(seen.runs) == 2
    assert _PREAMBLE not in written
    assert _REFUSED_PROSE not in written
    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == ["two facts"]


def _talking_tool_model(seen: _Seen) -> FunctionModel:
    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del info
        seen.runs.append(list(messages))
        if _returns(messages):
            yield "Both pages say the same."
            return
        yield "Reading the page first."
        yield {
            1: DeltaToolCall(
                name="read_page",
                json_args=json.dumps({"page": 1}),
                tool_call_id="page-1",
            ),
        }

    return FunctionModel(stream_function=_stream, model_name="test:talking-tool")


async def test_a_string_assistant_streams_its_text_around_its_tool_calls() -> None:
    thread = _Thread(_talking_tool_model(_Seen()), tools=[read_page])

    chunks = await thread.turn("read the page")

    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == [
        "Reading the page first.",
        "Both pages say the same.",
    ]
    assert [c["toolName"] for c in chunks if c["type"] == "tool-input-start"] == [
        "read_page",
    ]
