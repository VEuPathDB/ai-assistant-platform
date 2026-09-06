"""A tool's one-line summary patches the call it names and appends no part."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.sse import read_stream
from tests.synthetic import ADD_CALL_ID, ADD_PROMPT, SyntheticRuntime

from assistant_core.conversation.ui_message_reducer import reduce_chunks
from assistant_core.graph.stream_events import (
    ToolSummaryPayload,
    tool_summary_event,
)

SUMMARY_KIND = "data-tool-summary"
CALL = "call_3"
TOOL = "preview_eda_subset"
SUMMARY = "6 of 12 Sample"
MESSAGE_ID = "11111111-1111-1111-1111-111111111111"

_INPUT = {"entityId": "ENT_8151325d"}
_OUTPUT = {"entityCounts": [{"count": 6, "unfilteredCount": 12}]}


def _call_chunks() -> list[dict[str, object]]:
    return [
        {"type": "tool-input-start", "toolCallId": CALL, "toolName": TOOL},
        {
            "type": "tool-input-available",
            "toolCallId": CALL,
            "toolName": TOOL,
            "input": _INPUT,
        },
        {"type": "tool-output-available", "toolCallId": CALL, "output": _OUTPUT},
    ]


def _summary_chunk(summary: str, status: str | None = None) -> dict[str, object]:
    data: dict[str, object] = {"toolCallId": CALL, "summary": summary}
    if status is not None:
        data["status"] = status
    return {"type": SUMMARY_KIND, "data": data}


def _reduce(chunks: list[dict[str, object]]) -> dict[str, object]:
    return reduce_chunks(list(chunks), MESSAGE_ID)


def _parts(message: dict[str, object]) -> list[dict[str, object]]:
    parts = message["parts"]
    assert isinstance(parts, list)
    return parts


def test_the_summary_lands_on_the_call_it_names() -> None:
    message = _reduce([*_call_chunks(), _summary_chunk(SUMMARY, "ok")])

    assert _parts(message) == [
        {
            "type": f"tool-{TOOL}",
            "toolCallId": CALL,
            "state": "output-available",
            "input": _INPUT,
            "output": _OUTPUT,
            "summary": SUMMARY,
            "summaryStatus": "ok",
        },
    ]


def test_a_summary_naming_a_call_the_reducer_does_not_hold_is_ignored() -> None:
    stray = {
        "type": SUMMARY_KIND,
        "data": {"toolCallId": "call_gone", "summary": "nothing holds this call"},
    }

    message = _reduce([*_call_chunks(), stray])

    assert len(_parts(message)) == 1
    assert "summary" not in _parts(message)[0]


def test_a_later_summary_replaces_an_earlier_one() -> None:
    message = _reduce(
        [
            *_call_chunks(),
            _summary_chunk("12 of 12 Sample", "ok"),
            _summary_chunk(SUMMARY, "ok"),
        ],
    )

    assert _parts(message)[0]["summary"] == SUMMARY


def test_the_status_defaults_to_ok() -> None:
    message = _reduce([*_call_chunks(), _summary_chunk(SUMMARY)])

    assert _parts(message)[0]["summaryStatus"] == "ok"


def test_the_empty_status_reaches_the_part() -> None:
    message = _reduce([*_call_chunks(), _summary_chunk("0 of 12 Sample", "empty")])

    assert _parts(message)[0]["summaryStatus"] == "empty"


def test_a_summary_before_the_output_survives_the_output() -> None:
    start, available, output = _call_chunks()

    message = _reduce([start, available, _summary_chunk(SUMMARY, "warn"), output])

    part = _parts(message)[0]
    assert part["state"] == "output-available"
    assert part["summary"] == SUMMARY
    assert part["summaryStatus"] == "warn"


def test_a_summary_chunk_with_no_call_id_is_ignored() -> None:
    message = _reduce([*_call_chunks(), {"type": SUMMARY_KIND, "data": {}}])

    assert len(_parts(message)) == 1
    assert "summary" not in _parts(message)[0]


def test_the_builder_writes_the_chunk_the_document_shows() -> None:
    chunk = tool_summary_event(tool_call_id="call_a1", summary="6 of 12 Sample")

    assert chunk.model_dump(by_alias=True, mode="json", exclude_none=True) == {
        "type": SUMMARY_KIND,
        "data": {"toolCallId": "call_a1", "summary": "6 of 12 Sample", "status": "ok"},
    }


def test_the_payload_collapses_whitespace_around_and_inside_the_line() -> None:
    payload = ToolSummaryPayload(tool_call_id="c", summary="  6 of   12 Sample  ")

    assert payload.summary == "6 of 12 Sample"


@pytest.mark.parametrize(
    "summary",
    [
        "",
        "   ",
        "x" * 121,
        "two\nlines",
        "6 of 12 Sample.",
        "6 of 12 Sample \u2014 34,320 reads",
    ],
)
def test_the_payload_refuses_a_line_the_reader_cannot_use(summary: str) -> None:
    with pytest.raises(ValidationError):
        ToolSummaryPayload(tool_call_id="c", summary=summary)


async def test_a_tools_own_summary_reaches_the_log_and_the_reduced_message(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(ADD_PROMPT)

    frames = await read_stream(runtime.conversation_id)
    chunks = [frame.chunk() for frame in frames if not frame.is_done]
    summaries = [c for c in chunks if c["type"] == SUMMARY_KIND]
    message = reduce_chunks(chunks, MESSAGE_ID)
    call = next(
        part for part in _parts(message) if part.get("toolCallId") == ADD_CALL_ID
    )

    assert [c["data"] for c in summaries] == [
        {"toolCallId": ADD_CALL_ID, "summary": "2 plus 3 is 5", "status": "ok"},
    ]
    assert call["summary"] == "2 plus 3 is 5"
    assert call["output"] == 5
