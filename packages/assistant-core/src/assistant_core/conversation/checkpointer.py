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


@asynccontextmanager
async def lifespan_checkpointer(
    database_url: str,
    *,
    checkpoint_types: tuple[type, ...] = (),
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer for the app's lifetime.

    The saver bounds every call it serves, and closes its connection on exit.
    Calls ``setup()`` on entry to create checkpoint tables idempotently.
    ``checkpoint_types`` is the union the installed assistants declare; a
    caller that only needs the tables can leave it empty.
    """
    psycopg_url = to_psycopg_url(database_url)
    async with BoundedPostgresSaver.from_conn_string(
        psycopg_url, serde=build_checkpoint_serde(checkpoint_types)
    ) as saver:
        async with checkpoint_deadline("setup"):
            await saver.setup()
        yield saver
