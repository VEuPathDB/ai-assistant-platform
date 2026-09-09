"""The compaction gate, and what one run writes back."""

from __future__ import annotations

from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import ScratchpadCompaction
from assistant_core.persistence.repositories.scratchpad import ScratchpadRepository
from assistant_core.platform.db import DBSessionFactory
from assistant_core.scratchpad.compactor import (
    CompactionResult,
    CompactorDeps,
    compact_scratchpad,
)
from assistant_core.scratchpad.models import NoteCreate

MERGED = CompactionResult(
    notes=[NoteCreate(title="merged", summary="s", body="b")],
)


def _agent(output: CompactionResult) -> Agent[CompactorDeps, CompactionResult]:
    return Agent(
        TestModel(custom_output_args=output),
        deps_type=CompactorDeps,
        output_type=CompactionResult,
        instructions="Compact the notebook.",
    )


async def _fill(
    session: AsyncSession,
    conversation_id: UUID,
    count: int,
    *,
    pinned: bool = False,
) -> None:
    repo = ScratchpadRepository(session)
    for i in range(count):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=f"t{i}", summary="s", body="x" * 40, pinned=pinned),
        )
    await session.commit()


async def test_a_scratchpad_under_both_ceilings_is_left_alone(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 1)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
    )

    assert run is None


async def test_a_scratchpad_of_pinned_notes_never_triggers_the_compactor(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    """The gate counts what compaction can touch, so a pinned set cannot loop."""
    await _fill(db_session, conversation_id, 3, pinned=True)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
        count_threshold=1,
    )

    assert run is None


async def test_a_run_over_the_count_ceiling_replaces_the_unpinned_notes(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 3)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
        count_threshold=2,
    )

    assert run is not None
    assert run.before_count == 3
    assert run.after_count == 1
    assert run.trigger_reason == "count"
    assert run.model_id == "test"
    async with db_session_factory() as session:
        remaining = await ScratchpadRepository(session).list_notes(
            conversation_id=conversation_id,
            limit=100,
        )
    assert [note.title for note in remaining] == ["merged"]


async def test_a_run_over_the_token_ceiling_says_so(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 3)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
        tokens_threshold=0,
    )

    assert run is not None
    assert run.trigger_reason == "tokens"


async def test_a_run_over_both_ceilings_names_both(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 3)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
        count_threshold=2,
        tokens_threshold=0,
    )

    assert run is not None
    assert run.trigger_reason == "both"


async def test_the_replacement_set_is_trimmed_to_the_token_ceiling(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    """The oldest replacement goes first, so the notebook lands under budget."""
    await _fill(db_session, conversation_id, 3)
    oversized = CompactionResult(
        notes=[
            NoteCreate(title="dropped", summary="s", body="x" * 400),
            NoteCreate(title="kept", summary="s", body="y" * 400),
        ],
    )

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(oversized),
        count_threshold=2,
        tokens_threshold=100,
    )

    assert run is not None
    async with db_session_factory() as session:
        remaining = await ScratchpadRepository(session).list_notes(
            conversation_id=conversation_id,
            limit=100,
        )
    assert [note.title for note in remaining] == ["kept"]


async def test_a_run_is_logged_with_the_sizes_it_started_and_ended_at(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 3)

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=lambda: _agent(MERGED),
        count_threshold=2,
    )

    assert run is not None
    async with db_session_factory() as session:
        logged = (
            (
                await session.execute(
                    select(ScratchpadCompaction).where(
                        ScratchpadCompaction.conversation_id == conversation_id,
                    ),
                )
            )
            .scalars()
            .one()
        )
    assert logged.before_count == run.before_count
    assert logged.after_count == run.after_count
    assert logged.before_tokens == run.before_tokens
    assert logged.after_tokens == run.after_tokens
    assert logged.trigger_reason == "count"


class _CountingFactory:
    """Records how often the runtime asked the host to build a compactor."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Agent[CompactorDeps, CompactionResult]:
        self.calls += 1
        return _agent(MERGED)


async def test_a_scratchpad_under_both_ceilings_never_builds_the_agent(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    """The host pays for a compactor per compaction, not per turn."""
    await _fill(db_session, conversation_id, 1)
    factory = _CountingFactory()

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=factory,
    )

    assert run is None
    assert factory.calls == 0


async def test_a_run_builds_the_agent_once(
    db_session: AsyncSession,
    db_session_factory: DBSessionFactory,
    conversation_id: UUID,
) -> None:
    await _fill(db_session, conversation_id, 3)
    factory = _CountingFactory()

    run = await compact_scratchpad(
        conversation_id=conversation_id,
        db_session_factory=db_session_factory,
        agent=factory,
        count_threshold=2,
    )

    assert run is not None
    assert factory.calls == 1
