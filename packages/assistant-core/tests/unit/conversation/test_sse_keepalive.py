"""The chat SSE stream stays open while the event tail is silent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from assistant_core.conversation import event_stream
from assistant_core.platform.config import RuntimeSettings

_SILENCE_SECONDS = 0.4
_KEEPALIVE_SECONDS = 0.05
# A tail that never waits must outlast a stalled loop, not a fast one.
_LONG_KEEPALIVE_SECONDS = 30.0
_KEEPALIVE_FRAME = ": keep-alive\n\n"


async def _silent_tail(
    *,
    conversation_id: UUID,
    after: int,
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    """Three events with a silence between the first two."""
    del conversation_id, after
    yield 11, {"type": "text-start", "id": "a"}
    await asyncio.sleep(_SILENCE_SECONDS)
    yield 12, {"type": "text-delta", "id": "a", "delta": "x"}
    yield 13, {"type": "done"}


async def _busy_tail(
    *,
    conversation_id: UUID,
    after: int,
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    del conversation_id, after
    yield 11, {"type": "text-start", "id": "a"}
    yield 12, {"type": "text-delta", "id": "a", "delta": "x"}
    yield 13, {"type": "done"}


async def _frames(tail: Any, interval: float = _KEEPALIVE_SECONDS) -> list[str]:
    with (
        patch.object(event_stream, "replay_and_tail", tail),
        patch.object(
            event_stream,
            "get_runtime_settings",
            return_value=MagicMock(sse_keepalive_seconds=interval),
        ),
    ):
        return [
            frame
            async for frame in event_stream.iter_sse(
                conversation_id=uuid4(),
                after=0,
            )
        ]


async def test_keepalive_comments_fill_the_silence_between_two_events() -> None:
    frames = await _frames(_silent_tail)

    data_frames = [frame for frame in frames if frame != _KEEPALIVE_FRAME]
    keepalive_positions = [
        index for index, frame in enumerate(frames) if frame == _KEEPALIVE_FRAME
    ]

    assert keepalive_positions, frames
    assert (
        frames.index(data_frames[0])
        < min(keepalive_positions)
        < frames.index(data_frames[1])
    )


async def test_keepalive_comments_leave_ids_and_payloads_untouched() -> None:
    frames = await _frames(_silent_tail)

    data_frames = [frame for frame in frames if frame != _KEEPALIVE_FRAME]

    assert [frame.splitlines()[0] for frame in data_frames] == [
        "id: 11",
        "id: 12",
        "id: 13",
    ]
    assert json.loads(data_frames[0].split("data: ", 1)[1]) == {
        "type": "text-start",
        "id": "a",
    }
    assert data_frames[-1] == "id: 13\ndata: [DONE]\n\n"


async def test_a_tail_that_never_goes_quiet_sends_no_keepalive() -> None:
    frames = await _frames(_busy_tail, _LONG_KEEPALIVE_SECONDS)

    assert _KEEPALIVE_FRAME not in frames


def test_the_shipped_keepalive_interval_is_fifteen_seconds() -> None:
    assert RuntimeSettings.model_fields["sse_keepalive_seconds"].get_default() == 15


def test_a_keepalive_interval_below_one_second_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        RuntimeSettings(sse_keepalive_seconds=0)

    assert "sse_keepalive_seconds" in str(excinfo.value)
