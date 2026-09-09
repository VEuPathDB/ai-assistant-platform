"""The scratchpad index an agent reads at the top of its instructions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from assistant_core.scratchpad.models import Note

_EMPTY_BLOCK = "## Scratchpad (empty)\n\nNo notes yet."


class ScratchpadGuidance(BaseModel):
    """What a host tells its agent about keeping notes.

    The runtime renders the index; the coaching is the host's, because it
    names the work the agent does. ``empty`` and ``populated`` reach the
    index; ``promote`` reaches the ``promote_to_memory`` tool description.
    """

    model_config = ConfigDict(frozen=True)

    empty: str = ""
    populated: str = ""
    promote: str = ""


_NO_GUIDANCE = ScratchpadGuidance()


def _format_entry(note: Note) -> str:
    return f"  [{note.id}] {note.title}\n             {note.summary}"


def _with_guidance(body: str, guidance: str) -> str:
    return f"{body}\n\n{guidance}" if guidance else body


def render_scratchpad(
    notes: list[Note],
    *,
    total_count: int,
    guidance: ScratchpadGuidance = _NO_GUIDANCE,
    budget_chars: int = 10000,
) -> str:
    """The index for one thread, inside ``budget_chars`` where it can be.

    A pinned note is never dropped, so a scratchpad of pinned notes can
    exceed the budget.
    """
    if total_count == 0:
        return _with_guidance(_EMPTY_BLOCK, guidance.empty)

    pinned = [n for n in notes if n.pinned]
    recent = [n for n in notes if not n.pinned]
    header = f"## Scratchpad ({total_count} notes, {len(pinned)} pinned)"

    def _assemble(kept: list[Note]) -> str:
        sections: list[str] = [header]
        if pinned:
            sections.append("### Pinned")
            sections.extend(_format_entry(n) for n in pinned)
        if kept:
            sections.append("### Recent")
            sections.extend(_format_entry(n) for n in kept)
        return _with_guidance("\n".join(sections), guidance.populated)

    # The unpinned notes arrive newest first, so popping the tail drops the
    # oldest one.
    trimmed = list(recent)
    while trimmed and len(_assemble(trimmed)) > budget_chars:
        trimmed.pop()
    return _assemble(trimmed)
