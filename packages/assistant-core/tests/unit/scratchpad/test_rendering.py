"""The scratchpad index an agent reads, and the guidance its host supplies."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from assistant_core.scratchpad.models import Note
from assistant_core.scratchpad.rendering import (
    ScratchpadGuidance,
    render_scratchpad,
)

GUIDANCE = ScratchpadGuidance(
    empty="Save the runs you tried and the dead ends you found.",
    populated="Pin what the answer rests on before you end the turn.",
)


def _note(
    *,
    nid: str,
    title: str,
    summary: str = "s",
    pinned: bool = False,
    body_len: int = 40,
) -> Note:
    now = datetime.now(UTC)
    return Note(
        id=nid,
        conversation_id=uuid4(),
        title=title,
        summary=summary,
        body="x" * body_len,
        tags=[],
        pinned=pinned,
        body_tokens=body_len // 4,
        created_at=now,
        updated_at=now,
    )


def test_an_empty_scratchpad_says_so_and_carries_the_hosts_empty_guidance() -> None:
    out = render_scratchpad([], total_count=0, guidance=GUIDANCE)

    assert out.startswith("## Scratchpad (empty)")
    assert "No notes yet." in out
    assert out.endswith("Save the runs you tried and the dead ends you found.")


def test_a_host_that_supplies_no_guidance_gets_the_index_alone() -> None:
    out = render_scratchpad([], total_count=0)

    assert out == "## Scratchpad (empty)\n\nNo notes yet."


def test_the_header_counts_every_note_and_the_pinned_ones() -> None:
    notes = [
        _note(nid="n-aaa111", title="Pinned A", pinned=True),
        _note(nid="n-bbb222", title="Recent A"),
    ]

    out = render_scratchpad(notes, total_count=7, guidance=GUIDANCE)

    assert out.startswith("## Scratchpad (7 notes, 1 pinned)")


def test_a_populated_index_lists_both_sections_with_ids_and_summaries() -> None:
    notes = [
        _note(nid="n-aaa111", title="Pinned A", summary="pinned summary", pinned=True),
        _note(nid="n-bbb222", title="Recent A", summary="recent summary"),
    ]

    out = render_scratchpad(notes, total_count=2, guidance=GUIDANCE)

    assert "### Pinned" in out
    assert "  [n-aaa111] Pinned A\n             pinned summary" in out
    assert "### Recent" in out
    assert "  [n-bbb222] Recent A\n             recent summary" in out
    assert out.endswith("Pin what the answer rests on before you end the turn.")


def test_the_budget_drops_the_oldest_unpinned_notes() -> None:
    """The list arrives newest first, so the tail is what goes."""
    notes = [_note(nid=f"n-{i:06x}", title=f"T{i}") for i in range(5)]

    out = render_scratchpad(notes, total_count=5, budget_chars=120)

    assert len(out) == 106
    assert [f"T{i}" for i in range(5) if f"T{i}" in out] == ["T0", "T1"]


def test_the_budget_never_drops_a_pinned_note() -> None:
    notes = [
        _note(nid="n-pin", title="PINNED_KEEP", pinned=True),
        *[_note(nid=f"n-{i:06x}", title=f"T{i}") for i in range(5)],
    ]

    out = render_scratchpad(notes, total_count=6, budget_chars=50)

    assert len(out) == 81
    assert "PINNED_KEEP" in out
    assert [f"T{i}" for i in range(5) if f"T{i}" in out] == []
