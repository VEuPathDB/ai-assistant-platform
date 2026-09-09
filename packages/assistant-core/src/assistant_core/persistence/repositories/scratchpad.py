"""Reads and writes for the scratchpad tables. Every method returns a model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import ScratchpadCompaction, ScratchpadNote
from assistant_core.scratchpad.ids import approx_body_tokens, mint_note_id
from assistant_core.scratchpad.models import (
    CompactionRun,
    Note,
    NoteCreate,
    NoteUpdate,
)


def _row_to_note(row: ScratchpadNote) -> Note:
    return Note.model_validate(row, from_attributes=True)


class ScratchpadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _row(self, conversation_id: UUID, note_id: str) -> ScratchpadNote | None:
        stmt = select(ScratchpadNote).where(
            and_(
                ScratchpadNote.id == note_id,
                ScratchpadNote.conversation_id == conversation_id,
            ),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        conversation_id: UUID,
        data: NoteCreate,
    ) -> Note:
        row = ScratchpadNote(
            id=mint_note_id(),
            conversation_id=conversation_id,
            title=data.title,
            summary=data.summary,
            body=data.body,
            tags=list(data.tags),
            pinned=data.pinned,
            body_tokens=approx_body_tokens(data.body),
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return _row_to_note(row)

    async def get(self, *, conversation_id: UUID, note_id: str) -> Note | None:
        row = await self._row(conversation_id, note_id)
        return _row_to_note(row) if row is not None else None

    async def update(
        self,
        *,
        conversation_id: UUID,
        note_id: str,
        patch: NoteUpdate,
    ) -> Note:
        """:raises LookupError: If the note is not in this thread."""
        row = await self._require(conversation_id, note_id)
        if patch.title is not None:
            row.title = patch.title
        if patch.summary is not None:
            row.summary = patch.summary
        if patch.body is not None:
            row.body = patch.body
            row.body_tokens = approx_body_tokens(patch.body)
        if patch.tags is not None:
            row.tags = list(patch.tags)
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return _row_to_note(row)

    async def _require(self, conversation_id: UUID, note_id: str) -> ScratchpadNote:
        row = await self._row(conversation_id, note_id)
        if row is None:
            msg = f"note not found: {note_id}"
            raise LookupError(msg)
        return row

    async def delete(self, *, conversation_id: UUID, note_id: str) -> bool:
        stmt = delete(ScratchpadNote).where(
            and_(
                ScratchpadNote.id == note_id,
                ScratchpadNote.conversation_id == conversation_id,
            ),
        )
        result = cast("CursorResult[object]", await self.session.execute(stmt))
        return (result.rowcount or 0) > 0

    async def delete_notes_from(
        self,
        *,
        conversation_id: UUID,
        cutoff: datetime,
    ) -> int:
        """Delete the notes written at or after ``cutoff``, and report how many."""
        stmt = delete(ScratchpadNote).where(
            and_(
                ScratchpadNote.conversation_id == conversation_id,
                ScratchpadNote.created_at >= cutoff,
            ),
        )
        result = cast("CursorResult[object]", await self.session.execute(stmt))
        return result.rowcount or 0

    async def set_pinned(
        self,
        *,
        conversation_id: UUID,
        note_id: str,
        pinned: bool,
    ) -> Note:
        """:raises LookupError: If the note is not in this thread."""
        row = await self._require(conversation_id, note_id)
        row.pinned = pinned
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return _row_to_note(row)

    async def list_notes(
        self,
        *,
        conversation_id: UUID,
        tag: str | None = None,
        pinned: bool | None = None,
        limit: int = 100,
    ) -> list[Note]:
        stmt = select(ScratchpadNote).where(
            ScratchpadNote.conversation_id == conversation_id,
        )
        if pinned is not None:
            stmt = stmt.where(ScratchpadNote.pinned == pinned)
        if tag is not None:
            stmt = stmt.where(ScratchpadNote.tags.op("@>")([tag.lower().strip()]))
        stmt = stmt.order_by(
            ScratchpadNote.pinned.desc(),
            ScratchpadNote.created_at.desc(),
        ).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_row_to_note(r) for r in rows]

    async def search_notes(
        self,
        *,
        conversation_id: UUID,
        query: str,
        limit: int = 10,
    ) -> list[Note]:
        phrase = query.strip()
        if not phrase:
            return []
        tsq = func.websearch_to_tsquery("english", phrase)
        stmt = (
            select(ScratchpadNote)
            .where(
                and_(
                    ScratchpadNote.conversation_id == conversation_id,
                    ScratchpadNote.fts.op("@@")(tsq),
                ),
            )
            .order_by(func.ts_rank(ScratchpadNote.fts, tsq).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_row_to_note(r) for r in rows]

    async def list_for_index_with_totals(
        self,
        *,
        conversation_id: UUID,
        recent_limit: int = 10,
    ) -> tuple[list[Note], int, int]:
        """The index notes and the totals, in one session visit."""
        notes = await self.list_for_index(
            conversation_id=conversation_id,
            recent_limit=recent_limit,
        )
        total_count, total_tokens = await self.totals(conversation_id=conversation_id)
        return notes, total_count, total_tokens

    async def list_for_index(
        self,
        *,
        conversation_id: UUID,
        recent_limit: int = 10,
    ) -> list[Note]:
        """The pinned notes oldest first, then the newest unpinned ones.

        The pinned notes come first so that they lead the rendered index.
        """
        pinned_stmt = (
            select(ScratchpadNote)
            .where(
                and_(
                    ScratchpadNote.conversation_id == conversation_id,
                    ScratchpadNote.pinned.is_(True),
                ),
            )
            .order_by(ScratchpadNote.created_at.asc())
        )
        recent_stmt = (
            select(ScratchpadNote)
            .where(
                and_(
                    ScratchpadNote.conversation_id == conversation_id,
                    ScratchpadNote.pinned.is_(False),
                ),
            )
            .order_by(ScratchpadNote.created_at.desc())
            .limit(recent_limit)
        )
        pinned = (await self.session.execute(pinned_stmt)).scalars().all()
        recent = (await self.session.execute(recent_stmt)).scalars().all()
        return [
            *(_row_to_note(r) for r in pinned),
            *(_row_to_note(r) for r in recent),
        ]

    async def totals(self, *, conversation_id: UUID) -> tuple[int, int]:
        """Count and size every note. The compactor reads the compactable half."""
        stmt = select(
            func.count(ScratchpadNote.id),
            func.coalesce(func.sum(ScratchpadNote.body_tokens), 0),
        ).where(ScratchpadNote.conversation_id == conversation_id)
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def compactable_totals(self, *, conversation_id: UUID) -> tuple[int, int]:
        """Count and size the unpinned notes, the subset compaction may replace."""
        stmt = select(
            func.count(ScratchpadNote.id),
            func.coalesce(func.sum(ScratchpadNote.body_tokens), 0),
        ).where(
            and_(
                ScratchpadNote.conversation_id == conversation_id,
                ScratchpadNote.pinned.is_(False),
            ),
        )
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def replace_non_pinned(
        self,
        *,
        conversation_id: UUID,
        new_notes: list[NoteCreate],
    ) -> list[Note]:
        """Delete the unpinned rows and insert the replacements, atomically."""
        async with self.session.begin_nested():
            await self.session.execute(
                delete(ScratchpadNote).where(
                    and_(
                        ScratchpadNote.conversation_id == conversation_id,
                        ScratchpadNote.pinned.is_(False),
                    ),
                ),
            )
            return [
                await self.create(conversation_id=conversation_id, data=data)
                for data in new_notes
            ]

    async def copy_notes_for_fork(
        self,
        *,
        source_conversation_id: UUID,
        target_conversation_id: UUID,
        cutoff: datetime | None,
    ) -> dict[str, str]:
        """Copy the notes the copied turns wrote, under fresh ids.

        ``cutoff`` is the time of the first message the fork leaves behind, so
        a note a later turn wrote never reaches the branch. The returned
        old-to-new id map lets a caller rewrite stored references.
        """
        stmt = select(ScratchpadNote).where(
            ScratchpadNote.conversation_id == source_conversation_id,
        )
        if cutoff is not None:
            stmt = stmt.where(ScratchpadNote.created_at < cutoff)
        rows = (
            (await self.session.execute(stmt.order_by(ScratchpadNote.created_at)))
            .scalars()
            .all()
        )
        id_map: dict[str, str] = {}
        for src in rows:
            new_id = mint_note_id()
            id_map[src.id] = new_id
            self.session.add(
                ScratchpadNote(
                    id=new_id,
                    conversation_id=target_conversation_id,
                    title=src.title,
                    summary=src.summary,
                    body=src.body,
                    tags=list(src.tags),
                    pinned=src.pinned,
                    body_tokens=src.body_tokens,
                    # Each copy keeps its source time, because a revert cuts
                    # on that value.
                    created_at=src.created_at,
                ),
            )
        await self.session.flush()
        return id_map

    async def log_compaction(self, *, run: CompactionRun) -> None:
        self.session.add(
            ScratchpadCompaction(
                conversation_id=run.conversation_id,
                triggered_at=run.triggered_at,
                before_count=run.before_count,
                after_count=run.after_count,
                before_tokens=run.before_tokens,
                after_tokens=run.after_tokens,
                model_id=run.model_id,
                cost_usd=run.cost_usd,
                trigger_reason=run.trigger_reason,
            ),
        )
        await self.session.flush()
