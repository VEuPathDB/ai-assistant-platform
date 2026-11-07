import json
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from tests._host_schema import HOST_USERS

from assistant_core.migrate import alembic_config, upgrade_head
from assistant_core.persistence.models import Base

BEFORE = "2026_09_24_0005"
_DROPPED = (
    "data-model-settings-delta",
    "data-tool-availability-delta",
    "data-capability-load-delta",
)


def _migrate_before(connection: Connection) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, BEFORE)


@pytest.fixture
async def engine(db_engine: AsyncEngine) -> AsyncGenerator[AsyncEngine]:
    name = "assistant_core_history_deltas"
    admin = create_async_engine(
        db_engine.url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin.connect() as connection:
        await connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
        await connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    await admin.dispose()
    fresh = create_async_engine(db_engine.url.set(database=name), poolclass=NullPool)
    try:
        yield fresh
    finally:
        await fresh.dispose()


async def test_the_chain_drops_the_history_deltas_a_thread_logged(
    engine: AsyncEngine,
) -> None:
    user_id, conversation_id = uuid4(), uuid4()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=[HOST_USERS])
        await connection.run_sync(_migrate_before)
        await connection.execute(insert(HOST_USERS).values(id=user_id))
        await connection.execute(
            text(
                "INSERT INTO conversations (id, user_id, site_id, name)"
                " VALUES (:id, :user_id, 'plasmodb', 'kinases')"
            ),
            {"id": str(conversation_id), "user_id": str(user_id)},
        )
        for kind in (*_DROPPED, "text-delta"):
            await connection.execute(
                text(
                    "INSERT INTO conversation_events (conversation_id, chunk)"
                    " VALUES (:conversation_id, CAST(:chunk AS jsonb))"
                ),
                {
                    "conversation_id": str(conversation_id),
                    "chunk": json.dumps({"type": kind, "data": {}}),
                },
            )
        await connection.run_sync(upgrade_head)
    async with engine.connect() as connection:
        kept = await connection.execute(
            text("SELECT chunk->>'type' FROM conversation_events")
        )

    assert list(kept.scalars()) == ["text-delta"]
