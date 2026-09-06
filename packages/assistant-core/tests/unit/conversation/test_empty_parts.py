"""EmptyPartGate keeps a text or reasoning part that stays empty off the log."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from assistant_core.conversation import event_writer
from assistant_core.conversation.empty_parts import EmptyPartGate


def _types(chunks: list[dict[str, Any]]) -> list[str]:
    return [str(c["type"]) for c in chunks]


def test_a_reasoning_part_with_no_delta_is_dropped_whole() -> None:
    gate = EmptyPartGate()
    out = [
        *gate.admit({"type": "reasoning-start", "id": "r1"}),
        *gate.admit({"type": "reasoning-end", "id": "r1"}),
        *gate.admit({"type": "tool-input-start", "toolCallId": "c1", "toolName": "t"}),
    ]
    assert _types(out) == ["tool-input-start"]


def test_a_reasoning_part_with_a_delta_arrives_intact_and_in_order() -> None:
    gate = EmptyPartGate()
    out = [
        *gate.admit({"type": "reasoning-start", "id": "r1"}),
        *gate.admit({"type": "reasoning-delta", "id": "r1", "delta": "weighing"}),
        *gate.admit({"type": "reasoning-end", "id": "r1"}),
    ]
    assert _types(out) == ["reasoning-start", "reasoning-delta", "reasoning-end"]


def test_an_empty_text_part_is_dropped_and_a_full_one_is_kept() -> None:
    gate = EmptyPartGate()
    out = [
        *gate.admit({"type": "text-start", "id": "t1"}),
        *gate.admit({"type": "text-end", "id": "t1"}),
        *gate.admit({"type": "text-start", "id": "t2"}),
        *gate.admit({"type": "text-delta", "id": "t2", "delta": "Done."}),
        *gate.admit({"type": "text-end", "id": "t2"}),
    ]
    assert [(c["type"], c["id"]) for c in out] == [
        ("text-start", "t2"),
        ("text-delta", "t2"),
        ("text-end", "t2"),
    ]


def test_two_held_parts_are_told_apart_by_id() -> None:
    gate = EmptyPartGate()
    out = [
        *gate.admit({"type": "reasoning-start", "id": "r1"}),
        *gate.admit({"type": "text-start", "id": "t1"}),
        *gate.admit({"type": "text-delta", "id": "t1", "delta": "x"}),
        *gate.admit({"type": "reasoning-end", "id": "r1"}),
        *gate.admit({"type": "text-end", "id": "t1"}),
    ]
    assert [(c["type"], c["id"]) for c in out] == [
        ("text-start", "t1"),
        ("text-delta", "t1"),
        ("text-end", "t1"),
    ]


def test_every_other_chunk_passes_through_unchanged() -> None:
    gate = EmptyPartGate()
    chunk = {
        "type": "data-tool-summary",
        "data": {"toolCallId": "c1", "summary": "3 studies"},
    }
    assert gate.admit(chunk) == [chunk]


async def test_the_writer_returns_the_last_written_id_for_a_held_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[str] = []

    async def _append(**kwargs: Any) -> int:
        written.append(str(kwargs["chunk"]["type"]))
        return len(written)

    monkeypatch.setattr(event_writer, "append_chunk", _append)
    writer = event_writer.ChatEventWriter(conversation_id=uuid4(), turn_id=uuid4())
    assert await writer.write({"type": "start"}) == 1
    assert await writer.write({"type": "reasoning-start", "id": "r1"}) == 1
    assert await writer.write({"type": "reasoning-end", "id": "r1"}) == 1
    assert (
        await writer.write(
            {"type": "tool-input-start", "toolCallId": "c1", "toolName": "t"}
        )
        == 2
    )
    assert written == ["start", "tool-input-start"]
