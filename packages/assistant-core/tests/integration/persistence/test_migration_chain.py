"""The chain this package ships builds the schema its models declare."""

from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, MetaData, String, Table, insert, inspect, select, text
from sqlalchemy.engine import Connection
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
    Conversation,
    ConversationEvent,
    MemoryTombstoneRow,
    Message,
)
from assistant_core.platform.context import DEFAULT_APPLICATION_ID

BASELINE = "2026_09_09_0001"
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

    assert list(stamped.scalars()) == [BASELINE]


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
        await session.commit()

        thread = (await session.execute(select(Conversation))).scalar_one()
        message = (await session.execute(select(Message))).scalar_one()
        event = (await session.execute(select(ConversationEvent))).scalar_one()
        tombstone = (await session.execute(select(MemoryTombstoneRow))).scalar_one()

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

            assert list(stamped.scalars()) == [BASELINE]
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
