from __future__ import annotations

from assistant_core.graph.stream_events import scratchpad_updated_event


def test_event_type() -> None:
    chunk = scratchpad_updated_event()
    assert chunk.type == "data-scratchpad-updated"


def test_event_data_empty() -> None:
    chunk = scratchpad_updated_event()
    assert chunk.data == {}
