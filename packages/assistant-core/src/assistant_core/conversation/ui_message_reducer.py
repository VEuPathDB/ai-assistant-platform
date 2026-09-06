from __future__ import annotations

from typing import Any

from assistant_core.conversation._chunk_handlers import _apply_chunk
from assistant_core.conversation._chunk_state import Chunk, _new_state


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
    "reduce_chunks",
    "split_into_turns",
    "system_message_chunk",
    "user_message_chunk",
]
