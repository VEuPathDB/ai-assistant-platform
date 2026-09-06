"""The wire itself: frames, cursors, comments and the terminator.

The reader is the strict parser in ``tests.sse``, and the tail runs against a
real Postgres LISTEN channel, so these are the frames a non-JS consumer sees.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, TextDeltaChunk
from tests.sse import DONE_PAYLOAD, KEEPALIVE_FRAME, Frame, parse_frame, read_stream
from tests.synthetic import PLAIN_PROMPT, SyntheticRuntime, dump_chunk

from assistant_core.conversation import event_stream
from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.conversation.ui_message_reducer import user_message_chunk
from assistant_core.platform.config import RuntimeSettings

_KEEPALIVE_SECONDS = 1
_SILENCE_SECONDS = 1.4
_ATTACH_SECONDS = 0.2
_READ_TIMEOUT_SECONDS = 20.0


@pytest.fixture
def fast_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = RuntimeSettings(
        database_url=os.environ["DATABASE_URL"],
        sse_keepalive_seconds=_KEEPALIVE_SECONDS,
    )
    monkeypatch.setattr(event_stream, "get_runtime_settings", lambda: settings)


async def _read_live(runtime: SyntheticRuntime) -> list[Frame]:
    async def _pump() -> list[Frame]:
        return [
            parse_frame(raw)
            async for raw in event_stream.iter_sse(
                conversation_id=runtime.conversation_id,
                after=0,
            )
        ]

    reader = asyncio.create_task(_pump())
    writer = ChatEventWriter(conversation_id=runtime.conversation_id, turn_id=uuid4())
    await asyncio.sleep(_ATTACH_SECONDS)
    await writer.write(dump_chunk(TextDeltaChunk(id="t1", delta="hello")))
    await asyncio.sleep(_SILENCE_SECONDS)
    await writer.write(dump_chunk(DoneChunk()))
    async with asyncio.timeout(_READ_TIMEOUT_SECONDS):
        return await reader


async def test_every_event_frame_carries_a_cursor_and_one_data_line(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    frames = await read_stream(runtime.conversation_id)

    assert frames
    for frame in frames:
        assert frame.event_id is not None
        assert frame.raw == f"id: {frame.event_id}\ndata: {frame.data}\n\n"
    types = [f.chunk()["type"] for f in frames if not f.is_done]
    assert types[0] == "start"


async def test_the_stream_ends_at_the_done_sentinel(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    frames = await read_stream(runtime.conversation_id)

    assert frames[-1].data == DONE_PAYLOAD
    assert DONE_PAYLOAD not in [f.data for f in frames[:-1]]


async def test_the_prompt_envelopes_stay_out_of_the_wire(
    runtime: SyntheticRuntime,
) -> None:
    writer = ChatEventWriter(conversation_id=runtime.conversation_id, turn_id=uuid4())
    await writer.write(
        user_message_chunk(message_id=str(uuid4()), parts=[{"type": "text"}]),
    )
    await runtime.run(PLAIN_PROMPT)

    frames = await read_stream(runtime.conversation_id)

    assert "user-message" not in [f.chunk()["type"] for f in frames if not f.is_done]


async def test_a_chunk_written_after_the_reader_attached_still_arrives(
    runtime: SyntheticRuntime,
    fast_keepalive: None,
) -> None:
    del fast_keepalive

    frames = await _read_live(runtime)

    deltas = [
        f.chunk()["delta"]
        for f in frames
        if not f.is_comment and not f.is_done and f.chunk()["type"] == "text-delta"
    ]
    assert deltas == ["hello"]
    assert frames[-1].is_done


async def test_a_silent_tail_sends_comment_frames_that_carry_no_cursor(
    runtime: SyntheticRuntime,
    fast_keepalive: None,
) -> None:
    del fast_keepalive

    frames = await _read_live(runtime)

    comments = [f for f in frames if f.is_comment]
    assert comments
    assert all(f.raw == KEEPALIVE_FRAME for f in comments)
    assert all(f.event_id is None and f.data is None for f in comments)
