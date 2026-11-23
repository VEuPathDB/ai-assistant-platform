from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, IsolationLevel
from sqlalchemy.ext.asyncio import AsyncEngine

from assistant_core.conversation.checkpointer import (
    lifespan_checkpointer,
    to_psycopg_url,
)
from assistant_core.platform.config import RuntimeSettings, use_settings_source

_INDEXES = (
    "checkpoints_thread_id_idx",
    "checkpoint_blobs_thread_id_idx",
    "checkpoint_writes_thread_id_idx",
)
_DEADLINE_SECONDS = 1.0


@pytest.fixture
async def fresh_database(db_engine: AsyncEngine) -> AsyncIterator[str]:
    name = f"checkpointer_setup_{os.getpid()}"
    admin = await db_engine.connect()
    await admin.execution_options(isolation_level="AUTOCOMMIT")
    await admin.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await admin.exec_driver_sql(f'CREATE DATABASE "{name}"')
    try:
        yield db_engine.url.set(database=name).render_as_string(hide_password=False)
    finally:
        await admin.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
def a_short_deadline(patch_app_db_engine: None) -> Iterator[None]:
    del patch_app_db_engine
    url = os.environ["DATABASE_URL"]
    use_settings_source(
        lambda: RuntimeSettings(
            database_url=url, checkpoint_timeout_seconds=_DEADLINE_SECONDS
        )
    )
    yield
    use_settings_source(lambda: RuntimeSettings(database_url=url))


async def _open_snapshot(url: str) -> AsyncConnection:
    reader = await AsyncConnection.connect(to_psycopg_url(url))
    await reader.set_isolation_level(IsolationLevel.REPEATABLE_READ)
    await reader.execute("SELECT 1")
    return reader


async def _index_validity(url: str) -> dict[str, bool]:
    async with await AsyncConnection.connect(to_psycopg_url(url)) as conn:
        cursor = await conn.execute(
            "SELECT c.relname, i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = ANY(%s)",
            (list(_INDEXES),),
        )
        return {str(name): bool(valid) for name, valid in await cursor.fetchall()}


async def test_the_setup_waits_out_a_snapshot_older_than_its_deadline(
    fresh_database: str, a_short_deadline: None
) -> None:
    del a_short_deadline
    reader = await _open_snapshot(fresh_database)

    async def release() -> None:
        await asyncio.sleep(_DEADLINE_SECONDS * 2.5)
        await reader.rollback()

    releasing = asyncio.create_task(release())
    try:
        async with lifespan_checkpointer(fresh_database):
            pass
    finally:
        await releasing
        await reader.close()

    assert await _index_validity(fresh_database) == dict.fromkeys(_INDEXES, True)


async def test_an_index_a_cancelled_setup_left_invalid_is_rebuilt(
    fresh_database: str,
) -> None:
    reader = await _open_snapshot(fresh_database)
    async with AsyncPostgresSaver.from_conn_string(
        to_psycopg_url(fresh_database)
    ) as saver:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(_DEADLINE_SECONDS):
                await saver.setup()
    await reader.close()
    left = await _index_validity(fresh_database)

    async with lifespan_checkpointer(fresh_database):
        pass

    assert (left, await _index_validity(fresh_database)) == (
        {"checkpoints_thread_id_idx": False},
        dict.fromkeys(_INDEXES, True),
    )
