"""A strict SSE reader, written from the protocol and not from the emitter.

The suite parses frames the way a non-JS consumer must: split on the blank
line, read ``id:`` and ``data:`` fields, treat a leading colon as a comment.
A frame the runtime emits that this reader cannot name is a protocol break.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from assistant_core.conversation.event_stream import iter_sse

DONE_PAYLOAD = "[DONE]"
KEEPALIVE_FRAME = ": keep-alive\n\n"


class MalformedFrameError(AssertionError):
    """A frame the wire protocol does not define."""

    def __init__(self, raw: str) -> None:
        super().__init__(f"frame is not id/data/comment: {raw!r}")
        self.raw = raw


@dataclass(frozen=True)
class Frame:
    """One SSE frame: its cursor, its payload, and the bytes it arrived as."""

    raw: str
    event_id: int | None = None
    data: str | None = None

    @property
    def is_comment(self) -> bool:
        return self.event_id is None and self.data is None

    @property
    def is_done(self) -> bool:
        return self.data == DONE_PAYLOAD

    def chunk(self) -> dict[str, Any]:
        assert self.data is not None
        parsed: dict[str, Any] = json.loads(self.data)
        return parsed


def parse_frame(raw: str) -> Frame:
    """Read one frame. Raises when it is neither an event nor a comment."""
    if not raw.endswith("\n\n"):
        raise MalformedFrameError(raw)
    lines = raw[:-2].split("\n")
    if all(line.startswith(":") for line in lines):
        return Frame(raw=raw)
    event_id: int | None = None
    data: str | None = None
    for line in lines:
        if line.startswith("id: "):
            cursor = line.removeprefix("id: ")
            if not cursor.isdigit():
                raise MalformedFrameError(raw)
            event_id = int(cursor)
        elif line.startswith("data: "):
            data = line.removeprefix("data: ")
        else:
            raise MalformedFrameError(raw)
    if event_id is None or data is None:
        raise MalformedFrameError(raw)
    return Frame(raw=raw, event_id=event_id, data=data)


async def read_stream(conversation_id: UUID, *, after: int = 0) -> list[Frame]:
    """Every frame from ``after`` up to and including the turn terminator."""
    return [
        parse_frame(raw)
        async for raw in iter_sse(conversation_id=conversation_id, after=after)
    ]
