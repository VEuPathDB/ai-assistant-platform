from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    OutputToolCallEvent,
    OutputToolResultEvent,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from assistant_core.conversation.vercel_adapter import PhaseStreamEmitter

_CALL = ToolCallPart(tool_name="count", args={"column": "x"}, tool_call_id="call_1")
_OUTPUT = ToolCallPart(
    tool_name="final_result", args={"note": "x"}, tool_call_id="call_1"
)


async def _events(*events: Any) -> AsyncIterator[Any]:
    for event in events:
        yield event


async def _chunks(*events: Any) -> list[dict[str, Any]]:
    emitter = PhaseStreamEmitter(message_id="m1")
    return [
        chunk.model_dump(by_alias=True, mode="json", exclude_none=True)
        async for chunk in emitter.chunks(_events(*events))
        if chunk.type in {"tool-output-error", "data-tool-summary"}
    ]


async def _results(result: RetryPromptPart | ToolReturnPart) -> list[dict[str, Any]]:
    return await _chunks(
        FunctionToolCallEvent(part=_CALL), FunctionToolResultEvent(part=result)
    )


async def test_a_call_handed_back_to_the_model_is_marked_corrected() -> None:
    retry = RetryPromptPart(
        content="dataset records cannot be counted by x.",
        tool_name="count",
        tool_call_id="call_1",
    )

    chunks = await _results(retry)

    assert chunks[1] == {
        "type": "data-tool-summary",
        "data": {
            "toolCallId": "call_1",
            "summary": "dataset records cannot be counted by x",
            "status": "corrected",
        },
    }
    assert chunks[0]["type"] == "tool-output-error"


async def test_arguments_the_tool_refuses_are_marked_corrected() -> None:
    retry = RetryPromptPart(
        content=[
            {
                "type": "missing",
                "loc": ("column",),
                "msg": "Field required",
                "input": {},
            }
        ],
        tool_name="count",
        tool_call_id="call_1",
    )

    chunks = await _results(retry)

    assert chunks[-1]["data"] == {
        "toolCallId": "call_1",
        "summary": "Sent with arguments the tool does not accept",
        "status": "corrected",
    }


async def test_a_failed_call_is_not_marked_corrected() -> None:
    failed = ToolReturnPart(
        tool_name="count",
        content="The site did not answer.",
        tool_call_id="call_1",
        outcome="failed",
    )

    chunks = await _results(failed)

    assert [chunk["type"] for chunk in chunks] == ["tool-output-error"]


async def test_an_output_handed_back_to_the_model_is_marked_corrected() -> None:
    retry = RetryPromptPart(
        content="This reply does not match what the turn did.",
        tool_name="final_result",
        tool_call_id="call_1",
    )

    chunks = await _chunks(
        OutputToolCallEvent(part=_OUTPUT), OutputToolResultEvent(part=retry)
    )

    assert [chunk["type"] for chunk in chunks] == [
        "tool-output-error",
        "data-tool-summary",
    ]
    assert chunks[1]["data"] == {
        "toolCallId": "call_1",
        "summary": "This reply does not match what the turn did",
        "status": "corrected",
    }
