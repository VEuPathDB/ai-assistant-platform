"""The reader the conformance suite uses accepts only the frames the spec defines.

A permissive parser would make the framing suite say nothing, so its refusals
are pinned here.
"""

from __future__ import annotations

import pytest
from tests.sse import KEEPALIVE_FRAME, MalformedFrameError, parse_frame


def test_an_event_frame_yields_its_cursor_and_its_payload() -> None:
    frame = parse_frame('id: 12\ndata: {"type":"text-end","id":"a"}\n\n')

    assert frame.event_id == 12
    assert frame.chunk() == {"type": "text-end", "id": "a"}
    assert not frame.is_comment


def test_a_comment_frame_carries_neither_cursor_nor_payload() -> None:
    frame = parse_frame(KEEPALIVE_FRAME)

    assert frame.is_comment
    assert frame.event_id is None
    assert frame.data is None


def test_the_terminator_frame_is_the_literal_sentinel() -> None:
    frame = parse_frame("id: 40\ndata: [DONE]\n\n")

    assert frame.is_done
    assert frame.event_id == 40


@pytest.mark.parametrize(
    "raw",
    [
        "id: 12\ndata: {}\n",
        "event: message\ndata: {}\n\n",
        "data: {}\n\n",
        "id: 12\n\n",
        "id: twelve\ndata: {}\n\n",
    ],
)
def test_a_frame_the_protocol_does_not_define_is_refused(raw: str) -> None:
    with pytest.raises(MalformedFrameError):
        parse_frame(raw)
