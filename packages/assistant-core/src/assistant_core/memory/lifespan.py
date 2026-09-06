from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig

from assistant_core.conversation.checkpointer import to_psycopg_url
from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS
from assistant_core.memory.embedding import embed_text


@asynccontextmanager
async def lifespan_memory_store(
    database_url: str,
) -> AsyncIterator[AsyncPostgresStore]:
    """Open the LangGraph ``AsyncPostgresStore`` with vector indexing.

    ``fields`` lists the stored payload keys LangGraph embeds, one
    vector per field per put. We point it at a single synthetic
    ``_embed_text`` key populated by :func:`assistant_core.memory.store._dump_for_store`
    so every memory gets exactly one embedding (kind + name + tags +
    summary concatenated). Listing multiple raw fields would cost 4x per
    put and force ``Item.score`` to reflect best-field-match rather than
    combined semantic similarity.
    """
    psycopg_url = to_psycopg_url(database_url)
    index_config: PostgresIndexConfig = {
        "dims": EMBEDDING_DIMENSIONS,
        "embed": embed_text,
        "fields": ["_embed_text"],
        "distance_type": "cosine",
    }
    async with AsyncPostgresStore.from_conn_string(
        psycopg_url,
        index=index_config,
    ) as store:
        await store.setup()
        try:
            yield store
        finally:
            await _end_batch_task(store)


async def _end_batch_task(store: AsyncPostgresStore) -> None:
    """End the batch task of a closing store.

    The store queues every operation onto one background task and holds only a
    weak reference to itself from it, so nothing ends that task when the store
    goes. The task is private to LangGraph and there is no public shutdown.
    """
    task = store._task
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
