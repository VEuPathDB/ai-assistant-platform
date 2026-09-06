"""``with_summary`` puts one line about a call onto that call's metadata."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.ui.vercel_ai.response_types import DataChunk
from pydantic_ai.usage import RunUsage

from assistant_core.graph.stream_events import (
    TOOL_SUMMARY_LIMIT,
    ToolSummaryPayload,
)
from assistant_core.graph.tool_summary import truncate_summary, with_summary


class _Value(BaseModel):
    total: int


def _stub_model() -> FunctionModel:
    def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(content="ok")])

    async def _stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        del messages, info
        yield "ok"

    return FunctionModel(_fn, stream_function=_stream, model_name="test")


def _ctx(tool_call_id: str | None = "call_a1") -> RunContext[None]:
    return RunContext(
        deps=None,
        model=_stub_model(),
        usage=RunUsage(),
        tool_call_id=tool_call_id,
    )


def _summaries(metadata: Any) -> list[DataChunk]:
    return [
        chunk
        for chunk in metadata
        if isinstance(chunk, DataChunk) and chunk.type == "data-tool-summary"
    ]


def test_summary_chunk_names_the_call() -> None:
    value = _Value(total=3)
    returned = with_summary(value, "3 studies matched heat shock", ctx=_ctx())

    assert returned.return_value is value
    chunks = _summaries(returned.metadata)
    assert len(chunks) == 1
    assert chunks[0].data == {
        "toolCallId": "call_a1",
        "summary": "3 studies matched heat shock",
        "status": "ok",
    }


def test_status_travels() -> None:
    returned = with_summary(
        _Value(total=0),
        "No study matched heat shock",
        ctx=_ctx(),
        status="empty",
    )
    assert _summaries(returned.metadata)[0].data["status"] == "empty"


def test_extra_chunks_come_before_the_summary() -> None:
    figure = DataChunk(type="data-eda.viz", data={})
    returned = with_summary(
        _Value(total=1),
        "6 of 12 Sample",
        ctx=_ctx(),
        extra=[figure],
    )
    assert returned.metadata[0] is figure
    assert returned.metadata[-1].type == "data-tool-summary"


def test_no_call_id_drops_the_summary_and_keeps_the_extras() -> None:
    figure = DataChunk(type="data-eda.viz", data={})
    returned = with_summary(
        _Value(total=1),
        "6 of 12 Sample",
        ctx=_ctx(tool_call_id=None),
        extra=[figure],
    )
    assert returned.metadata == [figure]
    assert _summaries(returned.metadata) == []


@pytest.mark.parametrize(
    "raw",
    [
        "Heat shock response in sensitive mutants " * 6,
        "Plasmodium falciparum \u03b1-tubulin, Smith\u2019s isolate",
        "first line\nsecond line\n",
        "The subset selects six samples.",
        "  spaced   out  ",
    ],
)
def test_a_line_from_outside_text_is_always_a_valid_summary(raw: str) -> None:
    """A study title never turns a tool call into a validation error."""
    value = _Value(total=1)
    returned = with_summary(value, raw, ctx=_ctx())

    assert returned.return_value is value
    line = _summaries(returned.metadata)[0].data["summary"]
    assert isinstance(line, str)
    ToolSummaryPayload(tool_call_id="call_a1", summary=line)


def test_a_summary_that_normalizes_to_nothing_emits_no_chunk() -> None:
    figure = DataChunk(type="data-eda.viz", data={})
    for raw in ("   ", "...", "\n\n", "\u2014"):
        returned = with_summary(_Value(total=1), raw, ctx=_ctx(), extra=[figure])
        assert _summaries(returned.metadata) == [], raw
        assert returned.metadata == [figure]


def test_truncate_cuts_on_a_word_boundary() -> None:
    text = "the quick brown fox " * 20
    cut = truncate_summary(text)
    assert len(cut) <= TOOL_SUMMARY_LIMIT
    assert cut.endswith("brown")
    assert "  " not in cut


def test_truncate_collapses_newlines() -> None:
    assert truncate_summary("first\nsecond") == "first second"


def test_truncate_drops_a_trailing_period() -> None:
    assert truncate_summary("I should read the search first.") == (
        "I should read the search first"
    )


def test_truncate_folds_text_to_ascii() -> None:
    assert truncate_summary("P. falciparum \u2014 alpha\u2010tubulin caf\u00e9") == (
        "P. falciparum alphatubulin cafe"
    )


def test_every_truncated_line_is_a_valid_summary() -> None:
    """Whatever a site or a user wrote, the line the chunk carries is legal."""
    for raw in (
        "x" * 400,
        "ends with a period.",
        "two\nlines and a curly \u2019quote\u2019",
        "\u03b1-tubulin \u2014 heat shock",
    ):
        with_summary(_Value(total=1), truncate_summary(raw), ctx=_ctx())


async def _plain(ctx: RunContext[None]) -> _Value:
    """Return the value with no summary."""
    del ctx
    return _Value(total=3)


async def _summarized(ctx: RunContext[None]) -> ToolReturn[_Value]:
    """Return the same value with a summary beside it."""
    return with_summary(_Value(total=3), "3 studies matched heat shock", ctx=ctx)


@pytest.mark.asyncio
async def test_the_model_reads_the_same_tool_return() -> None:
    """A summarized tool writes the same ``content`` into the history."""

    def _call_then_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        called = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if called:
            return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name="_plain", args={}, tool_call_id="p1"),
                ToolCallPart(tool_name="_summarized", args={}, tool_call_id="s1"),
            ],
        )

    agent: Agent[None, str] = Agent(
        FunctionModel(_call_then_answer, model_name="test"),
        output_type=str,
        tools=[_plain, _summarized],
    )
    result = await agent.run("go")
    returns = {
        part.tool_call_id: part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    assert returns["p1"].content == returns["s1"].content
