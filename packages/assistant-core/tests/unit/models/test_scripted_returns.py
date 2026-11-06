from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

from assistant_core.models.scripted import retried_returns, tool_return_parts

_RETRIED = ToolReturnPart(
    "count", "column x is not a field", tool_call_id="c1", outcome="retried"
)
_ANSWERED = ToolReturnPart("count", "132 rows", tool_call_id="c2")

_RUN: list[ModelMessage] = [
    ModelResponse(parts=[ToolCallPart("count", {"column": "x"}, tool_call_id="c1")]),
    ModelRequest(parts=[_RETRIED]),
    ModelResponse(parts=[ToolCallPart("count", {"column": "y"}, tool_call_id="c2")]),
    ModelRequest(parts=[_ANSWERED]),
]


def test_a_retried_call_is_not_a_tool_return() -> None:
    assert tool_return_parts(_RUN) == [_ANSWERED]


def test_a_retried_call_is_a_retry() -> None:
    assert retried_returns(_RUN) == [_RETRIED]
