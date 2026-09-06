"""The log outlives its readers: a new consumer resumes where the old one died."""

from __future__ import annotations

import asyncio

from tests.sse import Frame, read_stream
from tests.synthetic import ADD_PROMPT, PLAIN_PROMPT, SyntheticRuntime

from assistant_core.conversation.event_stream import (
    fetch_chunks_after,
    fetch_snapshot_chunks,
)
from assistant_core.conversation.ui_message_reducer import (
    reduce_chunks,
    split_into_turns,
)


async def test_a_reader_that_reconnects_at_a_cursor_gets_the_exact_remainder(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(ADD_PROMPT)
    live = await read_stream(runtime.conversation_id)
    cut = len(live) // 2
    resume_from = live[cut].event_id
    assert resume_from is not None

    resumed = await read_stream(runtime.conversation_id, after=resume_from)

    assert [f.raw for f in resumed] == [f.raw for f in live[cut + 1 :]]
    assert resumed[-1].is_done


async def test_every_cursor_the_stream_hands_out_is_strictly_increasing(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(ADD_PROMPT)

    frames = await read_stream(runtime.conversation_id)
    ids = [f.event_id for f in frames]

    assert all(i is not None for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


async def test_the_snapshot_rebuilds_the_message_the_live_stream_built(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(PLAIN_PROMPT)
    cursor, live = await fetch_chunks_after(runtime.conversation_id, 0)

    boundary, snapshot = await fetch_snapshot_chunks(runtime.conversation_id)

    assert snapshot == live
    assert boundary == cursor
    assert reduce_chunks(snapshot, str(outcome.turn_message_id)) == reduce_chunks(
        live,
        str(outcome.turn_message_id),
    )


async def test_the_snapshot_of_two_turns_replays_both_messages(
    runtime: SyntheticRuntime,
) -> None:
    first = await runtime.run(PLAIN_PROMPT)
    second = await runtime.run(ADD_PROMPT)

    _boundary, snapshot = await fetch_snapshot_chunks(runtime.conversation_id)
    turns = split_into_turns(snapshot)

    assert len(turns) == 2
    messages = [
        reduce_chunks(turn, str(outcome.turn_message_id))
        for turn, outcome in zip(turns, (first, second), strict=True)
    ]
    assert [m["id"] for m in messages] == [
        str(first.turn_message_id),
        str(second.turn_message_id),
    ]
    assert [p["text"] for p in messages[1]["parts"] if p["type"] == "text"] == [
        "Result: 5.",
    ]


async def test_two_threads_writing_at_once_never_see_each_other_s_rows(
    runtime: SyntheticRuntime,
    other_runtime: SyntheticRuntime,
) -> None:
    await asyncio.gather(
        runtime.run(PLAIN_PROMPT),
        other_runtime.run(ADD_PROMPT),
    )

    first = await read_stream(runtime.conversation_id)
    second = await read_stream(other_runtime.conversation_id)

    assert {f.event_id for f in first}.isdisjoint({f.event_id for f in second})
    assert _types(first)[0] == "start"
    assert _types(second)[0] == "start"
    assert "tool-input-available" not in _types(first)
    assert "tool-input-available" in _types(second)
    assert _deltas(first) == [f"You said: {PLAIN_PROMPT}"]
    assert _deltas(second) == ["Result: 5."]


def _types(frames: list[Frame]) -> list[str]:
    return [str(f.chunk()["type"]) for f in frames if not f.is_done]


def _deltas(frames: list[Frame]) -> list[str]:
    return [
        str(f.chunk()["delta"])
        for f in frames
        if not f.is_done and f.chunk()["type"] == "text-delta"
    ]
