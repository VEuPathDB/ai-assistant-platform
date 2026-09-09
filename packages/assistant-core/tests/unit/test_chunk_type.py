"""The log's chunk type is public, so a consumer reads no private module."""

from __future__ import annotations

from assistant_core.conversation import Chunk, Part


def test_a_chunk_is_the_json_object_the_log_stores() -> None:
    chunk: Chunk = {"type": "text-delta", "id": "t1", "delta": "hi"}

    assert chunk["type"] == "text-delta"


def test_a_part_is_the_json_object_a_message_holds() -> None:
    part: Part = {"type": "text", "text": "hi", "state": "done"}

    assert part["state"] == "done"
