"""The writer that owns the chunk log is what times the turn."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest

from assistant_core.conversation import event_writer
from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.platform.metrics import TurnTimeline


class _RecordingTimeline(TurnTimeline):
    """A timeline that keeps what it was told instead of recording it."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def observe(self, chunk: Mapping[str, Any]) -> None:
        self.seen.append(str(chunk["type"]))


@pytest.fixture
def logged(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every chunk the writer appended, with the database taken out."""
    rows: list[dict[str, Any]] = []

    async def _append(**kwargs: Any) -> int:
        rows.append(kwargs["chunk"])
        return len(rows)

    monkeypatch.setattr(event_writer, "append_chunk", _append)
    return rows


async def test_the_writer_reports_every_chunk_it_appends_to_the_timeline(
    logged: list[dict[str, Any]],
) -> None:
    writer = ChatEventWriter(conversation_id=uuid4(), turn_id=uuid4())
    timeline = _RecordingTimeline()
    writer.timeline = timeline

    await writer.write({"type": "start", "messageId": "m"})
    await writer.write({"type": "finish", "finishReason": "stop"})

    assert timeline.seen == ["start", "finish"]
    assert [chunk["type"] for chunk in logged] == ["start", "finish"]
