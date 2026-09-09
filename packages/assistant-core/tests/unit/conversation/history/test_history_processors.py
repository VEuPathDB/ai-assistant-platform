"""The processor list the package exports, run as one pipeline."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from assistant_core.conversation.history import (
    HISTORY_PROCESSORS,
    compact_history,
    elide_consumed,
    pair_orphans,
)


def _run(messages: list[ModelMessage]) -> list[ModelMessage]:
    out = list(messages)
    for processor in HISTORY_PROCESSORS:
        out = processor(out)
    return out


def _returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for msg in messages
        for part in msg.parts
        if isinstance(part, ToolReturnPart)
    ]


def test_the_list_is_pairing_then_elision_then_compaction() -> None:
    assert (pair_orphans, elide_consumed, compact_history) == HISTORY_PROCESSORS


def test_the_pipeline_answers_an_orphaned_call_with_a_placeholder() -> None:
    """A call the stream never answered leaves the pipeline paired."""
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="do the thing")]),
        ModelResponse(
            parts=[ToolCallPart(tool_name="echo", args={}, tool_call_id="c1")]
        ),
    ]

    out = _run(messages)

    returns = _returns(out)
    assert [part.tool_call_id for part in returns] == ["c1"]
    assert "not executed" in str(returns[0].content)


def test_the_pipeline_leaves_a_small_structured_return_whole() -> None:
    """A short result costs less to keep than a round trip to refetch."""
    payload = {"count": 132}
    messages: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="count them")]),
    ]
    for i in range(6):
        messages.append(
            ModelResponse(
                parts=[ToolCallPart(tool_name="echo", args={}, tool_call_id=f"c{i}")]
            )
        )
        messages.append(
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="echo", content=payload, tool_call_id=f"c{i}"
                    )
                ]
            )
        )
    messages.append(ModelResponse(parts=[TextPart(content="done")]))

    out = _run(messages)

    assert [part.content for part in _returns(out)] == [payload] * 6
