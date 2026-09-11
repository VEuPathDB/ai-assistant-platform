from __future__ import annotations

from datetime import UTC, datetime

from assistant_core.graph.stream_events import memory_retrieved_event
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import StoredMemory


def _stored(key: str, kind: str, name: str, score: float) -> StoredMemory:
    return StoredMemory(
        key=key,
        value=MemoryValue(
            kind=kind,
            name=name,
            summary=f"summary of {name}",
            content={},
            created_at=datetime.now(UTC),
        ),
        score=score,
    )


def test_memory_retrieved_event_shape() -> None:
    chunk = memory_retrieved_event(
        memories=[
            _stored("k1", "strategy", "first recalled note", 0.83),
            _stored("k2", "dataset", "second recalled note", 0.61),
        ]
    )
    assert chunk.type == "data-memory-retrieved"
    mems = chunk.data["memories"]
    assert [m["key"] for m in mems] == ["k1", "k2"]
    assert [m["kind"] for m in mems] == ["strategy", "dataset"]
    assert mems[0]["name"] == "first recalled note"
    assert mems[0]["summary"] == "summary of first recalled note"
    assert mems[0]["score"] == 0.83


def test_memory_retrieved_event_handles_none_score() -> None:
    stored = StoredMemory(
        key="k3",
        value=MemoryValue(
            kind="knowledge",
            name="fact",
            summary="s",
            content={},
            created_at=datetime.now(UTC),
        ),
        score=None,
    )
    chunk = memory_retrieved_event(memories=[stored])
    assert chunk.data["memories"][0]["score"] == 0.0
