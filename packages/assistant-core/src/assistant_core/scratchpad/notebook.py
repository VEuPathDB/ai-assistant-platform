"""One thread's scratchpad for a caller that holds a session factory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from assistant_core.persistence.repositories.scratchpad import ScratchpadRepository
from assistant_core.platform.db import DBSessionFactory
from assistant_core.scratchpad.models import (
    CompactionRun,
    Note,
    NoteCreate,
    NoteUpdate,
)


@dataclass(frozen=True)
class ScratchpadTotals:
    """Note counts and token sizes, whole and compactable.

    Compaction cannot touch a pinned note, so the gate reads the compactable
    subset while the reported sizes cover the whole scratchpad.
    """

    total_count: int
    total_tokens: int
    compactable_count: int
    compactable_tokens: int


@dataclass(frozen=True)
class CompactionFacts:
    """What the compactor knows before it writes the replacement notes."""

    triggered_at: datetime
    before_count: int
    before_tokens: int
    model_id: str
    cost_usd: Decimal
    trigger_reason: Literal["count", "tokens", "both"]


class ScratchpadNotebook:
    """The scratchpad of one thread, for a caller outside a request session.

    Every method owns its session and commits, so a tool never holds a
    transaction open across a model call. The thread is already resolved by
    the turn that opened it, so ownership is not checked here.
    """

    def __init__(
        self,
        db_session_factory: DBSessionFactory,
        conversation_id: UUID,
    ) -> None:
        self._factory = db_session_factory
        self._conversation_id = conversation_id

    async def create(self, data: NoteCreate) -> Note:
        async with self._factory() as session:
            created = await ScratchpadRepository(session).create(
                conversation_id=self._conversation_id,
                data=data,
            )
            await session.commit()
        return created

    async def update(self, note_id: str, patch: NoteUpdate) -> Note:
        """:raises LookupError: If the note is not in this thread."""
        async with self._factory() as session:
            updated = await ScratchpadRepository(session).update(
                conversation_id=self._conversation_id,
                note_id=note_id,
                patch=patch,
            )
            await session.commit()
        return updated

    async def delete(self, note_id: str) -> bool:
        async with self._factory() as session:
            ok = await ScratchpadRepository(session).delete(
                conversation_id=self._conversation_id,
                note_id=note_id,
            )
            if ok:
                await session.commit()
        return ok

    async def set_pinned(self, note_id: str, *, pinned: bool) -> Note:
        """:raises LookupError: If the note is not in this thread."""
        async with self._factory() as session:
            updated = await ScratchpadRepository(session).set_pinned(
                conversation_id=self._conversation_id,
                note_id=note_id,
                pinned=pinned,
            )
            await session.commit()
        return updated

    async def get(self, note_id: str) -> Note | None:
        async with self._factory() as session:
            return await ScratchpadRepository(session).get(
                conversation_id=self._conversation_id,
                note_id=note_id,
            )

    async def index(self) -> tuple[list[Note], int]:
        """The index notes an agent is shown, and the size of the scratchpad."""
        async with self._factory() as session:
            notes, total, _ = await ScratchpadRepository(
                session,
            ).list_for_index_with_totals(conversation_id=self._conversation_id)
        return notes, total

    async def list_notes(
        self,
        *,
        tag: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> tuple[list[Note], int]:
        """The matching notes, and the size of the whole scratchpad."""
        async with self._factory() as session:
            repo = ScratchpadRepository(session)
            notes = await repo.list_notes(
                conversation_id=self._conversation_id,
                tag=tag,
                pinned=pinned,
                limit=limit,
            )
            total, _ = await repo.totals(conversation_id=self._conversation_id)
        return notes, total

    async def search_notes(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> tuple[list[Note], int]:
        """The notes matching ``query``, and the size of the whole scratchpad."""
        async with self._factory() as session:
            repo = ScratchpadRepository(session)
            hits = await repo.search_notes(
                conversation_id=self._conversation_id,
                query=query,
                limit=limit,
            )
            total, _ = await repo.totals(conversation_id=self._conversation_id)
        return hits, total

    async def total_notes(self) -> int:
        async with self._factory() as session:
            total, _ = await ScratchpadRepository(session).totals(
                conversation_id=self._conversation_id,
            )
        return total

    async def compaction_totals(self) -> ScratchpadTotals:
        async with self._factory() as session:
            repo = ScratchpadRepository(session)
            compactable_count, compactable_tokens = await repo.compactable_totals(
                conversation_id=self._conversation_id,
            )
            total_count, total_tokens = await repo.totals(
                conversation_id=self._conversation_id,
            )
        return ScratchpadTotals(
            total_count=total_count,
            total_tokens=total_tokens,
            compactable_count=compactable_count,
            compactable_tokens=compactable_tokens,
        )

    async def notes_to_compact(self, *, limit: int = 1000) -> list[Note]:
        async with self._factory() as session:
            return await ScratchpadRepository(session).list_notes(
                conversation_id=self._conversation_id,
                pinned=False,
                limit=limit,
            )

    async def commit_compaction(
        self,
        new_notes: list[NoteCreate],
        facts: CompactionFacts,
    ) -> CompactionRun:
        """Replace the unpinned notes and log the run, in one transaction."""
        async with self._factory() as session:
            repo = ScratchpadRepository(session)
            await repo.replace_non_pinned(
                conversation_id=self._conversation_id,
                new_notes=new_notes,
            )
            after_count, after_tokens = await repo.totals(
                conversation_id=self._conversation_id,
            )
            run = CompactionRun(
                conversation_id=self._conversation_id,
                triggered_at=facts.triggered_at,
                before_count=facts.before_count,
                after_count=after_count,
                before_tokens=facts.before_tokens,
                after_tokens=after_tokens,
                model_id=facts.model_id,
                cost_usd=facts.cost_usd,
                trigger_reason=facts.trigger_reason,
            )
            await repo.log_compaction(run=run)
            await session.commit()
        return run
