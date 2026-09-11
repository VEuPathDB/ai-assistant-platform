"""The tools an agent uses to keep notes for the thread it is working on."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import ValidationError
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import RunContext

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.graph.stream_events import scratchpad_updated_event
from assistant_core.graph.tool_summary import with_summary
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore
from assistant_core.platform.logging import get_logger
from assistant_core.platform.pydantic_base import CamelModel
from assistant_core.scratchpad.models import (
    Note,
    NoteCreate,
    NoteDetail,
    NoteListResult,
    NoteRef,
    NoteSearchResult,
    NoteUpdate,
)
from assistant_core.scratchpad.notebook import ScratchpadNotebook

logger = get_logger(__name__)

_MSG_MISSING_CTX = "scratchpad unavailable: missing conversation context"
_MSG_MEMORY_UNAVAILABLE = "memory store unavailable"
_MSG_NO_SCRATCHPAD = "The scratchpad is unavailable on this thread"


class ScratchpadUnavailable(CamelModel):
    """What a scratchpad tool returns when the turn carries no thread."""

    ok: Literal[False] = False
    code: Literal["NOT_FOUND"] = "NOT_FOUND"
    message: str = _MSG_MISSING_CTX


def _ref_payload(note: Note) -> dict[str, object]:
    return NoteRef.model_validate(note, from_attributes=True).model_dump(
        by_alias=True,
        mode="json",
    )


def _note_payload(note: Note) -> dict[str, object]:
    return NoteDetail.model_validate(note, from_attributes=True).model_dump(
        by_alias=True,
        mode="json",
    )


def _notebook(ctx: RunContext[AssistantDeps]) -> ScratchpadNotebook | None:
    """This thread's scratchpad, or None when it is unreachable.

    None is a permanent condition. A caller reports it as a plain tool
    result, never as a retry.
    """
    factory = ctx.deps.db_session_factory
    conversation_id = ctx.deps.conversation_id
    if factory is None or conversation_id is None:
        return None
    return ScratchpadNotebook(factory, conversation_id)


def _not_found_msg(note_id: str) -> str:
    return f"note id {note_id!r} not found - call list_notes() to see current notes"


def _no_scratchpad[T](
    ctx: RunContext[AssistantDeps],
) -> ToolReturn[T | ScratchpadUnavailable]:
    payload: T | ScratchpadUnavailable = ScratchpadUnavailable()
    return with_summary(payload, _MSG_NO_SCRATCHPAD, ctx=ctx, status="warn")


async def note(
    ctx: RunContext[AssistantDeps],
    title: str,
    summary: str,
    body: str,
    tags: list[str] | None = None,
    *,
    pinned: bool = False,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    """Save a scratchpad note.

    Use liberally: before moving on from anything promising, save what you
    learned. Over-noting is cheaper than re-discovering. Keep ``summary`` to
    roughly 280 characters (a one-line gist); put detail in ``body``.
    """
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    try:
        data = NoteCreate(
            title=title,
            summary=summary,
            body=body,
            pinned=pinned,
            tags=[] if tags is None else tags,
        )
    except ValidationError as exc:
        msg = f"invalid note payload: {exc}"
        raise ModelRetry(msg) from exc

    created = await notebook.create(data)

    logger.info(
        "scratchpad.note_created",
        conversation_id=str(ctx.deps.conversation_id),
        note_id=created.id,
        title=created.title,
    )
    return with_summary(
        _ref_payload(created),
        f"Note saved: {created.title}",
        ctx=ctx,
        extra=[scratchpad_updated_event()],
    )


async def update_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    """Update fields on an existing note. Omitted fields are unchanged.

    Keep ``summary`` to roughly 280 characters; put detail in ``body``.
    """
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    try:
        patch = NoteUpdate(title=title, summary=summary, body=body, tags=tags)
    except ValidationError as exc:
        msg = f"invalid update payload: {exc}"
        raise ModelRetry(msg) from exc

    try:
        updated = await notebook.update(note_id, patch)
    except LookupError as exc:
        raise ModelRetry(_not_found_msg(note_id)) from exc

    return with_summary(
        _ref_payload(updated),
        f"Note updated: {updated.title}",
        ctx=ctx,
        extra=[scratchpad_updated_event()],
    )


async def delete_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
) -> ToolReturn[str | ScratchpadUnavailable]:
    """Remove a note. Use when a newer note supersedes it."""
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    if not await notebook.delete(note_id):
        raise ModelRetry(_not_found_msg(note_id))
    return with_summary(
        "deleted",
        "Note deleted",
        ctx=ctx,
        extra=[scratchpad_updated_event()],
    )


async def _set_pin(
    ctx: RunContext[AssistantDeps],
    note_id: str,
    *,
    pinned: bool,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    try:
        updated = await notebook.set_pinned(note_id, pinned=pinned)
    except LookupError as exc:
        raise ModelRetry(_not_found_msg(note_id)) from exc
    verb = "Pinned" if pinned else "Unpinned"
    return with_summary(
        _ref_payload(updated),
        f"{verb} {updated.title}",
        ctx=ctx,
        extra=[scratchpad_updated_event()],
    )


async def pin_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    """Pin a note so compaction never merges or drops it."""
    return await _set_pin(ctx, note_id, pinned=True)


async def unpin_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    """Unpin a previously pinned note."""
    return await _set_pin(ctx, note_id, pinned=False)


def _filter_description(tag: str | None, *, pinned: bool | None) -> str:
    parts: list[str] = []
    if tag is not None:
        parts.append(f"tag='{tag}'")
    if pinned is True:
        parts.append("pinned=true")
    if pinned is False:
        parts.append("pinned=false")
    return f" with {' and '.join(parts)}" if parts else ""


async def list_notes(
    ctx: RunContext[AssistantDeps],
    tag: str | None = None,
    *,
    pinned: bool | None = None,
    limit: int = 50,
) -> ToolReturn[NoteListResult | ScratchpadUnavailable]:
    """List notes (references only, no body). Optional tag and pin filter.

    Returns an envelope ``{totalNotes, matches, summary}``. ``totalNotes`` is
    the size of the whole scratchpad, so it separates "no matches" from
    "empty scratchpad".
    """
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    notes, total = await notebook.list_notes(tag=tag, pinned=pinned, limit=limit)

    matches = [NoteRef.model_validate(n, from_attributes=True) for n in notes]
    filter_desc = _filter_description(tag, pinned=pinned)
    if total == 0:
        summary = "No notes saved in this scratchpad yet."
    elif not matches:
        summary = f"No notes{filter_desc} (scratchpad has {total} notes total)."
    else:
        summary = f"{len(matches)} of {total} notes{filter_desc}."
    return with_summary(
        NoteListResult(total_notes=total, matches=matches, summary=summary),
        f"{len(matches)} notes",
        ctx=ctx,
        status="ok" if matches else "empty",
    )


async def search_notes(
    ctx: RunContext[AssistantDeps],
    query: str,
    limit: int = 10,
) -> ToolReturn[NoteSearchResult | ScratchpadUnavailable]:
    """Search title, summary and body for a word or a phrase.

    Returns an envelope ``{totalNotes, query, matches, summary}``. An empty
    ``matches`` with ``totalNotes > 0`` means the query missed; with
    ``totalNotes == 0`` it means the scratchpad is empty.
    """
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    hits, total = await notebook.search_notes(query, limit=limit)

    matches = [NoteRef.model_validate(n, from_attributes=True) for n in hits]
    if total == 0:
        summary = "No notes saved in this scratchpad yet."
    elif not matches:
        summary = (
            f"No notes match {query!r} "
            f"(scratchpad has {total} notes total - try list_notes to browse)."
        )
    else:
        summary = f"{len(matches)} of {total} notes matched {query!r}."
    return with_summary(
        NoteSearchResult(
            total_notes=total,
            matches=matches,
            summary=summary,
            query=query,
        ),
        f"{len(matches)} notes for {query}",
        ctx=ctx,
        status="ok" if matches else "empty",
    )


async def read_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
) -> ToolReturn[dict[str, object] | ScratchpadUnavailable]:
    """Fetch the full note, body included, by id."""
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    note_row = await notebook.get(note_id)
    if note_row is None:
        raise ModelRetry(_not_found_msg(note_id))
    return with_summary(_note_payload(note_row), f"Read {note_row.title}", ctx=ctx)


async def promote_note(
    ctx: RunContext[AssistantDeps],
    note_id: str,
    *,
    kind: str,
) -> ToolReturn[str | ScratchpadUnavailable]:
    """Write one note to long-term memory under the kind the host named.

    The note stays where it is; a new cross-thread memory is created.
    """
    notebook = _notebook(ctx)
    if notebook is None:
        return _no_scratchpad(ctx)
    store_raw = ctx.deps.memory_store
    user_id = ctx.deps.user_id
    if store_raw is None or user_id is None:
        raise ModelRetry(_MSG_MEMORY_UNAVAILABLE)

    note_row = await notebook.get(note_id)
    if note_row is None:
        raise ModelRetry(_not_found_msg(note_id))

    value = MemoryValue(
        kind=kind,
        name=note_row.title,
        summary=note_row.summary,
        tags=list(note_row.tags),
        site_id=ctx.deps.site_id,
        content={"body": note_row.body, "source_note_id": note_row.id},
        auto_retrieve=True,
        source_conversation_id=ctx.deps.conversation_id,
        created_at=datetime.now(UTC),
    )
    return with_summary(
        await MemoryStore(store=store_raw).put(user_id=user_id, value=value),
        f"Promoted {note_row.title} to memory",
        ctx=ctx,
    )
