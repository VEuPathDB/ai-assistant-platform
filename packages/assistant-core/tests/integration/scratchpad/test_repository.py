"""The scratchpad rows: what the repository writes, reads and replaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import ScratchpadCompaction, ScratchpadNote
from assistant_core.persistence.repositories.scratchpad import ScratchpadRepository
from assistant_core.scratchpad.models import CompactionRun, NoteCreate, NoteUpdate


async def _age_to(session: AsyncSession, note_id: str, when: datetime) -> None:
    """Move one note in time, so a cutoff can fall between two notes."""
    await session.execute(
        update(ScratchpadNote)
        .where(ScratchpadNote.id == note_id)
        .values(created_at=when),
    )


async def test_a_created_note_reads_back_with_its_minted_id_and_token_count(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    created = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(
            title="Leading candidate",
            summary="The nightly run returned 1200 rows",
            body="Full body of the note.",
            tags=["candidate"],
        ),
    )
    await db_session.commit()

    fetched = await repo.get(conversation_id=conversation_id, note_id=created.id)

    assert created.id.startswith("n-")
    assert fetched is not None
    assert fetched.title == "Leading candidate"
    assert fetched.body_tokens == len("Full body of the note.") // 4


async def test_a_new_body_refreshes_the_token_count(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    created = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="t", summary="s", body="x" * 40),
    )
    await db_session.commit()

    updated = await repo.update(
        conversation_id=conversation_id,
        note_id=created.id,
        patch=NoteUpdate(body="y" * 400),
    )
    await db_session.commit()

    assert updated.body == "y" * 400
    assert updated.body_tokens == 100


async def test_a_note_of_another_thread_is_not_found(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)

    assert await repo.get(conversation_id=conversation_id, note_id="n-nope") is None


async def test_the_index_leads_with_the_pinned_notes(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    for i in range(3):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=f"t{i}", summary="s", body="b"),
        )
    pinned = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="pinned", summary="s", body="b", pinned=True),
    )
    await db_session.commit()

    notes = await repo.list_for_index(
        conversation_id=conversation_id,
        recent_limit=10,
    )

    assert next(n.id for n in notes) == pinned.id
    assert len(notes) == 4


async def test_a_listing_filters_by_tag(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="a", summary="s", body="b", tags=["alpha"]),
    )
    await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="b", summary="s", body="b", tags=["beta"]),
    )
    await db_session.commit()

    alphas = await repo.list_notes(conversation_id=conversation_id, tag="alpha")

    assert [n.title for n in alphas] == ["a"]


async def test_the_full_text_search_ranks_the_note_that_holds_the_words(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(
            title="Nightly candidate",
            summary="Stage-differential, 1200 rows",
            body="Using threshold 2, gametocyte_vs_asexual.",
        ),
    )
    await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(
            title="Dead end",
            summary="Lost specificity",
            body="Do not retry.",
        ),
    )
    await db_session.commit()

    hits = await repo.search_notes(
        conversation_id=conversation_id,
        query="gametocyte threshold",
    )

    assert [n.title for n in hits] == ["Nightly candidate"]


async def test_an_empty_query_matches_nothing(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="t", summary="s", body="b"),
    )
    await db_session.commit()

    assert await repo.search_notes(conversation_id=conversation_id, query="  ") == []


async def test_a_pin_survives_the_write_and_the_read(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    created = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="t", summary="s", body="b"),
    )
    await db_session.commit()

    pinned = await repo.set_pinned(
        conversation_id=conversation_id,
        note_id=created.id,
        pinned=True,
    )
    await db_session.commit()

    assert pinned.pinned is True


async def test_a_deleted_note_is_gone(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    created = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="t", summary="s", body="b"),
    )
    await db_session.commit()

    deleted = await repo.delete(
        conversation_id=conversation_id,
        note_id=created.id,
    )
    await db_session.commit()

    assert deleted is True
    assert await repo.get(conversation_id=conversation_id, note_id=created.id) is None


async def test_the_totals_count_every_note_and_its_tokens(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    for i in range(5):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=f"t{i}", summary="s", body="x" * 40),
        )
    await db_session.commit()

    assert await repo.totals(conversation_id=conversation_id) == (5, 50)


async def test_the_compactable_totals_leave_the_pinned_notes_out(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    for i in range(3):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(
                title=f"pin{i}",
                summary="s",
                body="x" * 40,
                pinned=True,
            ),
        )
    for i in range(2):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=f"np{i}", summary="s", body="y" * 80),
        )
    await db_session.commit()

    assert await repo.totals(conversation_id=conversation_id) == (5, 70)
    assert await repo.compactable_totals(conversation_id=conversation_id) == (2, 40)


async def test_replacing_the_unpinned_notes_keeps_the_pinned_ones(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    pinned = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="pin", summary="s", body="b", pinned=True),
    )
    for title in ("old1", "old2"):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=title, summary="s", body="b"),
        )
    await db_session.commit()

    await repo.replace_non_pinned(
        conversation_id=conversation_id,
        new_notes=[NoteCreate(title="merged", summary="s", body="b")],
    )
    await db_session.commit()

    remaining = await repo.list_notes(conversation_id=conversation_id, limit=100)

    assert sorted(n.title for n in remaining) == ["merged", "pin"]
    assert any(n.id == pinned.id for n in remaining)


async def test_a_fork_copies_the_notes_written_before_the_cutoff(
    db_session: AsyncSession,
    conversation_id: UUID,
    branch_conversation_id: UUID,
) -> None:
    """A branch takes fresh ids, and a note a later turn wrote stays behind."""
    repo = ScratchpadRepository(db_session)
    kept = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="kept", summary="s", body="body of the kept note"),
    )
    later = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="later", summary="s", body="b"),
    )
    cutoff = datetime.now(UTC) + timedelta(minutes=1)
    await _age_to(db_session, later.id, cutoff + timedelta(minutes=1))
    await db_session.commit()

    id_map = await repo.copy_notes_for_fork(
        source_conversation_id=conversation_id,
        target_conversation_id=branch_conversation_id,
        cutoff=cutoff,
    )
    await db_session.commit()

    copied = await repo.list_notes(conversation_id=branch_conversation_id, limit=100)

    assert list(id_map) == [kept.id]
    assert id_map[kept.id] != kept.id
    assert [n.title for n in copied] == ["kept"]
    assert copied[0].body == "body of the kept note"
    assert copied[0].id == id_map[kept.id]


async def test_a_fork_with_no_cutoff_copies_every_note(
    db_session: AsyncSession,
    conversation_id: UUID,
    branch_conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    for title in ("one", "two"):
        await repo.create(
            conversation_id=conversation_id,
            data=NoteCreate(title=title, summary="s", body="b"),
        )
    await db_session.commit()

    id_map = await repo.copy_notes_for_fork(
        source_conversation_id=conversation_id,
        target_conversation_id=branch_conversation_id,
        cutoff=None,
    )
    await db_session.commit()

    copied = await repo.list_notes(conversation_id=branch_conversation_id, limit=100)

    assert len(id_map) == 2
    assert sorted(n.title for n in copied) == ["one", "two"]


async def test_a_revert_deletes_the_notes_at_and_after_its_cutoff(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    before = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="before", summary="s", body="b"),
    )
    after = await repo.create(
        conversation_id=conversation_id,
        data=NoteCreate(title="after", summary="s", body="b"),
    )
    cutoff = datetime.now(UTC) + timedelta(minutes=1)
    await _age_to(db_session, after.id, cutoff)
    await db_session.commit()

    removed = await repo.delete_notes_from(
        conversation_id=conversation_id,
        cutoff=cutoff,
    )
    await db_session.commit()

    remaining = await repo.list_notes(conversation_id=conversation_id, limit=100)

    assert removed == 1
    assert [n.id for n in remaining] == [before.id]


async def test_a_compaction_run_is_logged_with_its_cost(
    db_session: AsyncSession,
    conversation_id: UUID,
) -> None:
    repo = ScratchpadRepository(db_session)
    run = CompactionRun(
        conversation_id=conversation_id,
        triggered_at=datetime.now(UTC),
        before_count=9,
        after_count=2,
        before_tokens=900,
        after_tokens=120,
        model_id="openai:gpt-4.1-mini",
        cost_usd=Decimal("0.004200"),
        trigger_reason="count",
    )

    await repo.log_compaction(run=run)
    await db_session.commit()

    logged = (
        (
            await db_session.execute(
                select(ScratchpadCompaction).where(
                    ScratchpadCompaction.conversation_id == conversation_id,
                ),
            )
        )
        .scalars()
        .one()
    )

    assert logged.before_count == 9
    assert logged.after_count == 2
    assert logged.model_id == "openai:gpt-4.1-mini"
    assert logged.cost_usd == Decimal("0.004200")
    assert logged.trigger_reason == "count"
