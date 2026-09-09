from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import ConfigDict

from assistant_core.conversation import Chunk
from assistant_core.conversation._chunk_handlers import _apply_chunk
from assistant_core.conversation._chunk_state import _new_state
from assistant_core.platform.pydantic_base import CamelModel

# Section 6: a turn that ends any other way sends its message nothing more.
SUSPENDED_TURN_REASON = "other"


def reduce_chunks(
    chunks: list[Chunk],
    default_message_id: str,
) -> dict[str, Any]:
    state = _new_state(default_message_id)
    for chunk in chunks:
        _apply_chunk(state, chunk)
    return state.message


def split_into_turns(chunks: list[Chunk]) -> list[list[Chunk]]:
    """Split a chunk log into per-turn slices on ``done`` boundaries.

    Each slice ends with the ``done`` chunk that terminated it. A trailing
    slice with no ``done`` represents an in-flight turn the snapshot caught
    mid-stream.
    """
    turns: list[list[Chunk]] = []
    current: list[Chunk] = []
    for chunk in chunks:
        current.append(chunk)
        if chunk.get("type") == "done":
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


class OpenMessageRef(CamelModel):
    """The message a log left open, and the exclusive cursor a tail replays it from."""

    message_id: str
    after: int


class _LogChunk(CamelModel):
    model_config = ConfigDict(extra="ignore")

    type: str = ""
    message_id: str | None = None
    finish_reason: str | None = None


def open_message_of(entries: Sequence[tuple[int, Chunk]]) -> OpenMessageRef | None:
    """The message the log leaves open, and the cursor before its ``start``.

    A ``finish`` closes its message unless the turn suspended on a task.
    """
    open_message: OpenMessageRef | None = None
    previous = 0
    for cursor, chunk in entries:
        parsed = _LogChunk.model_validate(chunk)
        if parsed.type == "start" and parsed.message_id is not None:
            open_message = OpenMessageRef(message_id=parsed.message_id, after=previous)
        elif parsed.type == "finish" and parsed.finish_reason != SUSPENDED_TURN_REASON:
            open_message = None
        previous = cursor
    return open_message


USER_MESSAGE_CHUNK_TYPE = "user-message"
SYSTEM_MESSAGE_CHUNK_TYPE = "system-message"
ASSISTANT_MESSAGE_CHUNK_TYPE = "assistant-message"


def user_message_chunk(
    *,
    message_id: str,
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": USER_MESSAGE_CHUNK_TYPE,
        "message": {"id": message_id, "role": "user", "parts": parts},
    }


def system_message_chunk(
    *,
    message_id: str,
    parts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": SYSTEM_MESSAGE_CHUNK_TYPE,
        "message": {"id": message_id, "role": "system", "parts": parts},
    }


__all__ = [
    "ASSISTANT_MESSAGE_CHUNK_TYPE",
    "SYSTEM_MESSAGE_CHUNK_TYPE",
    "USER_MESSAGE_CHUNK_TYPE",
    "OpenMessageRef",
    "open_message_of",
    "reduce_chunks",
    "split_into_turns",
    "system_message_chunk",
    "user_message_chunk",
]
