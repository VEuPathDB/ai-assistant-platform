"""The chain this package ships builds the schema its models declare."""

from collections.abc import AsyncGenerator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, String, Table, insert, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tests._host_schema import HOST_BACKGROUND_TASKS, HOST_USERS

from assistant_core.migrate import VERSION_TABLE, include_object, upgrade_head
from assistant_core.persistence.models import (
    Base,
    ChatTurnCancellation,
    Conversation,
    ConversationEvent,
    MemoryTombstoneRow,
    Message,
    MonthlyUsage,
    ScratchpadCompaction,
    ScratchpadNote,
)
from assistant_core.platform.context import DEFAULT_APPLICATION_ID

HEAD = "2026_09_09_0003"
HOST_TABLES = [HOST_USERS, HOST_BACKGROUND_TASKS]

_STAMP = Table(
    VERSION_TABLE, MetaData(), Column("version_num", String(32), primary_key=True)
)

_NEW_THREAD = text(
    "INSERT INTO conversations (id, user_id, site_id, name)"
    " VALUES (:id, :user_id, 'plasmodb', 'kinases')"
)
_NEW_MESSAGE = text(
    "INSERT INTO messages (id, conversation_id, role)"
    " VALUES (:id, :conversation_id, 'assistant')"
)
_NEW_EVENT = text(
    "INSERT INTO conversation_events (conversation_id, chunk)"
    " VALUES (:conversation_id, :chunk)"
)
_NEW_TOMBSTONE = text(
    "INSERT INTO memory_tombstones (user_id, kind, content_hash, reason)"
    " VALUES (:user_id, 'case', 'abc', 'user_deleted')"
)
_NEW_STOP = text(
    "INSERT INTO chat_turn_cancellations (conversation_id, turn_id)"
    " VALUES (:conversation_id, :turn_id)"
)
_NEW_USAGE = text(
    "INSERT INTO monthly_usage (id, user_id, period_start)"
    " VALUES (:id, :user_id, DATE '2026-09-01')"
)
_NEW_NOTE = text(
    "INSERT INTO scratchpad_notes"
    " (id, conversation_id, title, summary, body, body_tokens)"
    " VALUES (:id, :conversation_id, 'a title', 'a summary', 'a body', 1)"
)
_NEW_COMPACTION = text(
    "INSERT INTO scratchpad_compactions (conversation_id, before_count,"
    " after_count, before_tokens, after_tokens, model_id, trigger_reason)"
    " VALUES (:conversation_id, 9, 2, 900, 120, 'openai:gpt-4.1-mini', 'count')"
)


async def _fresh_database(template: AsyncEngine, name: str) -> AsyncEngine:
    """A database of its own, so the chain runs against nothing it did not build."""
    admin = create_async_engine(
        template.url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin.connect() as connection:
        await connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
        await connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    await admin.dispose()
    return create_async_engine(template.url.set(database=name), poolclass=NullPool)


def _migrate(connection: Connection) -> None:
    upgrade_head(connection)


def _foreign_keys(connection: Connection, table: str) -> set[tuple[str, str, str]]:
    return {
        (
            key["constrained_columns"][0],
            key["referred_table"],
            key["referred_columns"][0],
        )
        for key in inspect(connection).get_foreign_keys(table)
    }


def _differences(connection: Connection) -> list[tuple[object, ...]]:
    """The operations autogenerate would write for this distribution."""
    context = MigrationContext.configure(
        connection,
        opts={"version_table": VERSION_TABLE, "include_object": include_object},
    )
    return compare_metadata(context, Base.metadata)


def _unfiltered_differences(connection: Connection) -> list[tuple[object, ...]]:
    """The operations autogenerate would write with no filter, host tables included."""
    context = MigrationContext.configure(
        connection, opts={"version_table": VERSION_TABLE}
    )
    return compare_metadata(context, Base.metadata)


@pytest.fixture(scope="module")
async def chain_engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine]:
    """An empty database carrying the host contract, then this package's chain."""
    engine = await _fresh_database(db_engine, "assistant_core_chain")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=HOST_TABLES)
        await connection.run_sync(_migrate)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_the_chain_builds_the_schema_the_models_declare(
    chain_engine: AsyncEngine,
) -> None:
    async with chain_engine.connect() as connection:
        differences = await connection.run_sync(_differences)

    assert differences == []


async def test_the_chain_closes_the_cycle_between_a_thread_and_a_message(
    chain_engine: AsyncEngine,
) -> None:
    """The two tables point at each other, so a metadata diff skips these keys."""
    async with chain_engine.connect() as connection:
        threads = await connection.run_sync(_foreign_keys, "conversations")
        messages = await connection.run_sync(_foreign_keys, "messages")

    assert threads == {
        ("user_id", "users", "id"),
        ("parent_conversation_id", "conversations", "id"),
        ("parent_message_id", "messages", "id"),
    }
    assert messages == {("conversation_id", "conversations", "id")}


async def test_the_chain_records_its_position_in_its_own_version_table(
    chain_engine: AsyncEngine,
) -> None:
    async with chain_engine.connect() as connection:
        stamped = await connection.execute(select(_STAMP.c.version_num))

    assert list(stamped.scalars()) == [HEAD]


async def test_a_thread_written_on_the_chain_schema_reads_back(
    chain_engine: AsyncEngine,
) -> None:
    """A row that names only the required columns takes the defaults the chain wrote."""
    user_id, conversation_id, message_id = uuid4(), uuid4(), uuid4()
    maker = async_sessionmaker(
        chain_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        await session.execute(
            _NEW_THREAD, {"id": str(conversation_id), "user_id": str(user_id)}
        )
        await session.execute(
            _NEW_MESSAGE,
            {"id": str(message_id), "conversation_id": str(conversation_id)},
        )
        await session.execute(
            _NEW_EVENT,
            {
                "conversation_id": str(conversation_id),
                "chunk": '{"type": "text-delta"}',
            },
        )
        await session.execute(_NEW_TOMBSTONE, {"user_id": str(user_id)})
        await session.execute(
            _NEW_STOP,
            {"conversation_id": str(conversation_id), "turn_id": str(uuid4())},
        )
        await session.execute(_NEW_USAGE, {"id": str(uuid4()), "user_id": str(user_id)})
        await session.execute(
            _NEW_NOTE,
            {"id": "n-abc123", "conversation_id": str(conversation_id)},
        )
        await session.execute(
            _NEW_COMPACTION,
            {"conversation_id": str(conversation_id)},
        )
        await session.commit()

        thread = (await session.execute(select(Conversation))).scalar_one()
        message = (await session.execute(select(Message))).scalar_one()
        event = (await session.execute(select(ConversationEvent))).scalar_one()
        tombstone = (await session.execute(select(MemoryTombstoneRow))).scalar_one()
        stop = (await session.execute(select(ChatTurnCancellation))).scalar_one()
        usage = (await session.execute(select(MonthlyUsage))).scalar_one()
        note = (await session.execute(select(ScratchpadNote))).scalar_one()
        compaction = (await session.execute(select(ScratchpadCompaction))).scalar_one()

    assert thread.assistant_id == "default"
    assert thread.application_id == DEFAULT_APPLICATION_ID
    assert thread.created_at is not None
    assert thread.updated_at is not None
    assert message.metadata_ == {}
    assert message.created_at is not None
    assert event.chunk == {"type": "text-delta"}
    assert event.task_id is None
    assert event.emitted_at is not None
    assert tombstone.application_id == DEFAULT_APPLICATION_ID
    assert tombstone.deleted_at is not None
    assert isinstance(thread.user_id, UUID)
    assert stop.requested_at is not None
    assert usage.application_id == DEFAULT_APPLICATION_ID
    assert usage.total_cost_usd == Decimal(0)
    assert usage.total_tokens == 0
    assert usage.updated_at is not None
    assert note.tags == []
    assert note.pinned is False
    assert note.created_at is not None
    assert note.updated_at is not None
    assert compaction.cost_usd == Decimal(0)
    assert compaction.triggered_at is not None


async def test_the_chain_leaves_tables_a_host_chain_already_created(
    db_engine: AsyncEngine,
) -> None:
    """A database built from the models is stamped, not rebuilt."""
    engine = await _fresh_database(db_engine, "assistant_core_stamped")
    kept = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(insert(HOST_USERS).values(id=kept))
            await connection.run_sync(_migrate)
        async with engine.connect() as connection:
            stamped = await connection.execute(select(_STAMP.c.version_num))
            survivors = await connection.execute(select(HOST_USERS.c.id))

            assert list(stamped.scalars()) == [HEAD]
            assert list(survivors.scalars()) == [kept]
    finally:
        await engine.dispose()


async def test_the_chain_refuses_a_database_that_holds_part_of_its_schema(
    db_engine: AsyncEngine,
) -> None:
    """A half-built database is named, not stamped over."""
    engine = await _fresh_database(db_engine, "assistant_core_partial")
    built = [*HOST_TABLES, Base.metadata.tables["memory_tombstones"]]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=built)
            with pytest.raises(RuntimeError) as caught:
                await connection.run_sync(_migrate)

        assert "present ['memory_tombstones']" in str(caught.value)
        assert "missing ['conversation_events', 'conversations', 'messages']" in str(
            caught.value
        )
    finally:
        await engine.dispose()


async def test_autogenerate_leaves_a_table_this_chain_does_not_own(
    db_engine: AsyncEngine,
) -> None:
    """A host table in the same database draws no operation from this chain."""
    engine = await _fresh_database(db_engine, "assistant_core_foreign")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=HOST_TABLES)
            await connection.run_sync(_migrate)
            await connection.exec_driver_sql(
                "CREATE TABLE gene_sets (id integer PRIMARY KEY)"
            )
        async with engine.connect() as connection:
            filtered = await connection.run_sync(_differences)
            unfiltered = await connection.run_sync(_unfiltered_differences)

        assert filtered == []
        assert [(entry[0], entry[1].name) for entry in unfiltered] == [
            ("remove_table", "gene_sets")
        ]
    finally:
        await engine.dispose()


async def test_the_chain_leaves_the_stop_and_cost_tables_a_host_already_built(
    db_engine: AsyncEngine,
) -> None:
    """A host chain that built all six tables is stamped at the head, not rebuilt."""
    engine = await _fresh_database(db_engine, "assistant_core_stop_cost")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_migrate)
        async with engine.connect() as connection:
            stamped = await connection.execute(select(_STAMP.c.version_num))

            assert list(stamped.scalars()) == [HEAD]
    finally:
        await engine.dispose()


async def test_the_chain_refuses_a_database_that_holds_one_of_the_two_new_tables(
    db_engine: AsyncEngine,
) -> None:
    """A half-built pair is named, not stamped over."""
    engine = await _fresh_database(db_engine, "assistant_core_half_pair")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql("DROP TABLE scratchpad_notes")
            await connection.exec_driver_sql("DROP TABLE scratchpad_compactions")
            await connection.exec_driver_sql("DROP TABLE monthly_usage")
            with pytest.raises(RuntimeError) as caught:
                await connection.run_sync(_migrate)

        assert "present ['chat_turn_cancellations']" in str(caught.value)
        assert "missing ['monthly_usage']" in str(caught.value)
    finally:
        await engine.dispose()


async def test_a_stop_row_goes_when_its_thread_does(
    chain_engine: AsyncEngine,
) -> None:
    """The cascade the chain wrote leaves no stop request behind a deleted thread."""
    user_id, conversation_id = uuid4(), uuid4()
    maker = async_sessionmaker(
        chain_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        await session.execute(
            _NEW_THREAD, {"id": str(conversation_id), "user_id": str(user_id)}
        )
        await session.execute(
            _NEW_STOP,
            {"conversation_id": str(conversation_id), "turn_id": str(uuid4())},
        )
        await session.commit()
        await session.execute(
            text("DELETE FROM conversations WHERE id = :id"),
            {"id": str(conversation_id)},
        )
        await session.commit()

        left = await session.execute(
            select(ChatTurnCancellation).where(
                ChatTurnCancellation.conversation_id == conversation_id,
            ),
        )

    assert list(left.scalars()) == []


async def test_the_chain_refuses_a_database_that_holds_one_scratchpad_table(
    db_engine: AsyncEngine,
) -> None:
    """The scratchpad pair is refused half-built, the way the others are."""
    engine = await _fresh_database(db_engine, "assistant_core_half_scratchpad")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql("DROP TABLE scratchpad_compactions")
            with pytest.raises(RuntimeError) as caught:
                await connection.run_sync(_migrate)

        assert "present ['scratchpad_notes']" in str(caught.value)
        assert "missing ['scratchpad_compactions']" in str(caught.value)
    finally:
        await engine.dispose()


async def test_a_note_goes_when_its_thread_does(
    chain_engine: AsyncEngine,
) -> None:
    """The cascade the chain wrote leaves no note behind a deleted thread."""
    user_id, conversation_id = uuid4(), uuid4()
    maker = async_sessionmaker(
        chain_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        await session.execute(
            _NEW_THREAD, {"id": str(conversation_id), "user_id": str(user_id)}
        )
        await session.execute(
            _NEW_NOTE,
            {"id": "n-cascade", "conversation_id": str(conversation_id)},
        )
        await session.execute(
            _NEW_COMPACTION,
            {"conversation_id": str(conversation_id)},
        )
        await session.commit()
        await session.execute(
            text("DELETE FROM conversations WHERE id = :id"),
            {"id": str(conversation_id)},
        )
        await session.commit()

        notes = await session.execute(
            select(ScratchpadNote).where(
                ScratchpadNote.conversation_id == conversation_id,
            ),
        )
        compactions = await session.execute(
            select(ScratchpadCompaction).where(
                ScratchpadCompaction.conversation_id == conversation_id,
            ),
        )

    assert list(notes.scalars()) == []
    assert list(compactions.scalars()) == []


async def test_the_chain_refuses_a_reason_the_gate_cannot_produce(
    chain_engine: AsyncEngine,
) -> None:
    """The check constraint the revision wrote holds at the database."""
    user_id, conversation_id = uuid4(), uuid4()
    maker = async_sessionmaker(
        chain_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        await session.execute(insert(HOST_USERS).values(id=user_id))
        await session.execute(
            _NEW_THREAD, {"id": str(conversation_id), "user_id": str(user_id)}
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO scratchpad_compactions (conversation_id,"
                    " before_count, after_count, before_tokens, after_tokens,"
                    " model_id, trigger_reason)"
                    " VALUES (:conversation_id, 1, 1, 1, 1, 'm', 'sometimes')"
                ),
                {"conversation_id": str(conversation_id)},
            )
        await session.rollback()
