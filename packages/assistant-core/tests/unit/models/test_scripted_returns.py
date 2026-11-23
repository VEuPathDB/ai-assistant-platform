from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant_core.capabilities.refused_calls import CallRefused, MarkRefusedCalls
from assistant_core.models.scripted import refused_returns, tool_return_parts

_RETRIED = ToolReturnPart(
    "count", "column x is not a field", tool_call_id="c1", outcome="retried"
)
_ANSWERED = ToolReturnPart("count", "132 rows", tool_call_id="c2")

_REFUSAL = "count needs a column"

_RUN: list[ModelMessage] = [
    ModelResponse(parts=[ToolCallPart("count", {"column": "x"}, tool_call_id="c1")]),
    ModelRequest(parts=[_RETRIED]),
    ModelResponse(parts=[ToolCallPart("count", {"column": "y"}, tool_call_id="c2")]),
    ModelRequest(parts=[_ANSWERED]),
]


def _refused_run() -> list[ModelMessage]:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if len(messages) > 1:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("count", {}, tool_call_id="c3")])

    agent = Agent(FunctionModel(model), capabilities=[MarkRefusedCalls()])

    @agent.tool_plain
    def count() -> str:
        raise CallRefused(_REFUSAL)

    return agent.run_sync("count the rows").all_messages()


def test_a_retried_call_is_not_a_tool_return() -> None:
    assert tool_return_parts(_RUN) == [_ANSWERED]


def test_a_retried_call_is_a_refusal() -> None:
    assert refused_returns(_RUN) == [_RETRIED]


def test_a_call_the_tool_refused_is_a_refusal_and_no_return() -> None:
    run = _refused_run()

    assert (
        [part.content for part in refused_returns(run)],
        tool_return_parts(run),
    ) == ([_REFUSAL], [])
