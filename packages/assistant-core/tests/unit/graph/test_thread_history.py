"""The trim keeps only the history a new prompt can run over."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from assistant_core.graph.thread_history import settled_history


def _prompt(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _answer(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def test_a_settled_exchange_survives_the_trim() -> None:
    messages = [_prompt("hello"), _answer("hi")]

    assert settled_history(messages) == messages


def test_a_trailing_tool_call_is_trimmed() -> None:
    settled = [_prompt("hello"), _answer("hi")]
    messages = [
        *settled,
        _prompt("count them"),
        ModelResponse(parts=[ToolCallPart(tool_name="count", tool_call_id="c1")]),
    ]

    assert settled_history(messages) == settled


def test_a_trailing_suspended_answer_is_trimmed() -> None:
    """pydantic-ai refuses a new prompt over a suspended trailing response."""
    settled = [_prompt("hello"), _answer("hi")]
    suspended = ModelResponse(parts=[TextPart(content="thinking")], state="suspended")
    messages = [*settled, _prompt("go on"), suspended]

    assert settled_history(messages) == settled


def test_an_incomplete_trailing_answer_survives_the_trim() -> None:
    """Only the two states pydantic-ai refuses count as unsettled."""
    messages = [
        _prompt("hello"),
        ModelResponse(parts=[TextPart(content="hi")], state="incomplete"),
    ]

    assert settled_history(messages) == messages
