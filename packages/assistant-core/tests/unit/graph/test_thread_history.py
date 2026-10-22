"""The trim keeps only the history a new prompt can run over."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
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


def _calls(*call_ids: str) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(tool_name="final_result", tool_call_id=call_id)
            for call_id in call_ids
        ],
    )


def _returned(*call_ids: str) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="final_result",
                content="Final result processed.",
                tool_call_id=call_id,
            )
            for call_id in call_ids
        ],
    )


def test_a_call_whose_result_follows_it_ends_an_exchange() -> None:
    messages = [_prompt("hello"), _calls("c1"), _returned("c1")]

    assert settled_history(messages) == messages


def test_a_call_left_without_a_result_is_trimmed() -> None:
    settled = [_prompt("hello"), _answer("hi")]
    messages = [*settled, _prompt("count"), _calls("c1", "c2"), _returned("c1")]

    assert settled_history(messages) == settled
