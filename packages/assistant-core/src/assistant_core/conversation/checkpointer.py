from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from sqlalchemy.engine import make_url

from assistant_core.conversation.deadline import checkpoint_deadline
from assistant_core.conversation.serde import build_checkpoint_serde


def to_psycopg_url(database_url: str) -> str:
    """Strip ``+asyncpg`` from a SQLAlchemy URL for psycopg.

    The app uses asyncpg via SQLAlchemy (``postgresql+asyncpg://...``); the
    LangGraph checkpoint store uses psycopg directly. Both speak Postgres,
    but psycopg cannot parse the SQLAlchemy ``+asyncpg`` driver suffix.
    """
    url = make_url(database_url)
    if url.drivername in {"postgresql+asyncpg", "postgresql+psycopg_async"}:
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


class BoundedCheckpointCalls(BaseCheckpointSaver[str]):
    """Give every checkpoint round trip of a turn a deadline.

    A checkpointer that stops answering holds the turn and its worker slot,
    because nothing else ends the wait.
    """

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        async with checkpoint_deadline("get"):
            return await super().aget_tuple(config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        async with checkpoint_deadline("put"):
            return await super().aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        async with checkpoint_deadline("put writes"):
            await super().aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        async with checkpoint_deadline("delete"):
            await super().adelete_thread(thread_id)


class BoundedPostgresSaver(BoundedCheckpointCalls, AsyncPostgresSaver):
    """The Postgres checkpointer, under the turn's deadline."""


_CHECKPOINT_TABLES = ["checkpoints", "checkpoint_blobs", "checkpoint_writes"]

_INVALID_INDEXES = """
SELECT index_class.relname
FROM pg_index
JOIN pg_class AS index_class ON index_class.oid = pg_index.indexrelid
JOIN pg_class AS table_class ON table_class.oid = pg_index.indrelid
WHERE NOT pg_index.indisvalid
  AND table_class.relname = ANY(%s)
  AND table_class.relnamespace = current_schema()::regnamespace
"""


async def _rebuild_invalid_indexes(conn: AsyncConnection[DictRow]) -> None:
    cursor = await conn.execute(_INVALID_INDEXES, (_CHECKPOINT_TABLES,))
    for row in await cursor.fetchall():
        await conn.execute(
            sql.SQL("REINDEX INDEX CONCURRENTLY {}").format(
                sql.Identifier(row["relname"])
            )
        )


@asynccontextmanager
async def lifespan_checkpointer(
    database_url: str,
    *,
    checkpoint_types: tuple[type, ...] = (),
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer for the app's lifetime.

    The saver bounds every call it serves, and closes its connection on exit.
    Calls ``setup()`` on entry to create checkpoint tables idempotently. The
    setup is not bounded: a concurrent index build waits for older snapshots,
    and a cancelled build leaves an invalid index, which the entry rebuilds.
    ``checkpoint_types`` is the union the installed assistants declare; a
    caller that only needs the tables can leave it empty.
    """
    psycopg_url = to_psycopg_url(database_url)
    async with await AsyncConnection.connect(
        psycopg_url, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        saver = BoundedPostgresSaver(
            conn, serde=build_checkpoint_serde(checkpoint_types)
        )
        await saver.setup()
        await _rebuild_invalid_indexes(conn)
        yield saver
