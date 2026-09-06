"""A gate that keeps a text or reasoning part off the log when it stays empty."""

from __future__ import annotations

from typing import Any

_HELD_STARTS: dict[str, tuple[str, str]] = {
    "text-start": ("text-delta", "text-end"),
    "reasoning-start": ("reasoning-delta", "reasoning-end"),
}
_RELEASING = {delta: start for start, (delta, _end) in _HELD_STARTS.items()}
_CLOSING = {end: start for start, (_delta, end) in _HELD_STARTS.items()}


class EmptyPartGate:
    """Holds a part's start chunk until its first delta arrives.

    A start followed by its end with no delta between them is dropped whole,
    so a reader never receives a part that carries nothing. Every other chunk
    passes through unchanged and in order.
    """

    def __init__(self) -> None:
        self._held: dict[str, dict[str, Any]] = {}

    def admit(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        kind = str(chunk.get("type", ""))
        part_id = str(chunk.get("id", ""))
        if kind in _HELD_STARTS:
            self._held[part_id] = chunk
            return []
        if kind in _RELEASING:
            held = self._held.pop(part_id, None)
            return [chunk] if held is None else [held, chunk]
        if kind in _CLOSING and self._held.pop(part_id, None) is not None:
            return []
        return [chunk]
