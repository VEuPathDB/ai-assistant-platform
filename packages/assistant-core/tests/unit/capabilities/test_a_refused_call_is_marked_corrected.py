from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)

from assistant_core.capabilities.refused_calls import CallRefused, MarkRefusedCalls
from assistant_core.conversation.vercel_adapter import PhaseStreamEmitter


async def _call_once(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    del info
    if len(messages) == 1:
        yield {0: DeltaToolCall(name="count", json_args="{}", tool_call_id="call_1")}
    else:
        yield "done"


async def _summaries(error: ToolFailed) -> list[dict[str, Any]]:
    agent: Agent[None, str] = Agent(
        FunctionModel(stream_function=_call_once),
        capabilities=[MarkRefusedCalls[None]()],
    )

    @agent.tool_plain
    def count() -> str:
        raise error

    seen: list[Any] = []

    async def keep(_ctx: RunContext[None], events: AsyncIterable[Any]) -> None:
        seen.extend([event async for event in events])

    await agent.run("go", event_stream_handler=keep)
    emitter = PhaseStreamEmitter(message_id="m1")
    return [
        chunk.model_dump(by_alias=True, mode="json", exclude_none=True)["data"]
        async for chunk in emitter.chunks(_replayed(seen))
        if chunk.type == "data-tool-summary"
    ]


async def _replayed(events: list[Any]) -> AsyncIterator[Any]:
    for event in events:
        yield event


async def test_a_call_a_tool_refuses_is_marked_corrected() -> None:
    summaries = await _summaries(CallRefused("This read already answered."))

    assert summaries == [
        {
            "toolCallId": "call_1",
            "summary": "This read already answered",
            "status": "corrected",
        }
    ]


async def test_a_call_that_failed_is_not_marked() -> None:
    assert await _summaries(ToolFailed("The site did not answer.")) == []
