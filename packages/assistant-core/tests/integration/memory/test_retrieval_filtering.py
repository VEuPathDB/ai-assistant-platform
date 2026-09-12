"""Cross-namespace retrieval honors the caller's scope rule and auto_retrieve.

The scope rule is the caller's predicate: a host that scopes memories to a data
host passes one, and a memory that names no host is kept by it. A memory
written with ``auto_retrieve=False`` is withheld from graph-time retrieval
whatever the predicate says.

These run against the real pgvector HNSW store + embeddings (only the LLM is
ever mocked), so they also cover the ``semantic_search`` -> filter -> rerank
merge across the namespaces.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.memory.retrieval import (
    RetrievalScope,
    retrieve_relevant_memories,
)
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore

# The kinds an assistant declares; this suite uses two of the synthetic host's.
DECLARED_KINDS: tuple[str, ...] = ("note", "knowledge")


def _note(name: str, site_id: str | None, *, auto_retrieve: bool = True) -> MemoryValue:
    return MemoryValue(
        kind="note",
        name=name,
        summary=f"measured counts note {name} on {site_id}",
        tags=[site_id] if site_id else [],
        site_id=site_id,
        content={"note_id": name},
        auto_retrieve=auto_retrieve,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_retrieval_applies_the_callers_scope_rule(
    db_cleaner: None,
    patch_app_db_engine: None,
) -> None:
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()

    async with lifespan_memory_store(database_url) as raw:
        store = MemoryStore(store=raw)
        await store.put(user_id=user_id, value=_note("here-note", "site-a"))
        await store.put(user_id=user_id, value=_note("elsewhere-note", "site-b"))
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="scope-free-fact",
                summary="measured counts are reported per thousand",
                tags=[],
                site_id=None,
                content={"fact": "counts"},
                created_at=datetime.now(UTC),
            ),
        )

        results = await retrieve_relevant_memories(
            store=store,
            user_id=user_id,
            query="measured counts note",
            scope=RetrievalScope(
                kinds=DECLARED_KINDS,
                keep=lambda memory: memory.site_id in (None, "site-a"),
                top_k=8,
            ),
        )
        names = {m.value.name for m in results}
        assert "here-note" in names, "an in-scope memory must be retrieved"
        assert "scope-free-fact" in names, "a memory with no scope must be retrieved"
        assert "elsewhere-note" not in names, "the predicate must drop the rest"


@pytest.mark.asyncio
async def test_retrieval_withholds_auto_retrieve_false(
    db_cleaner: None,
    patch_app_db_engine: None,
) -> None:
    """A memory flagged ``auto_retrieve=False`` is excluded from graph-time
    retrieval even when it is the strongest semantic match the predicate keeps.
    """
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()

    async with lifespan_memory_store(database_url) as raw:
        store = MemoryStore(store=raw)
        await store.put(user_id=user_id, value=_note("auto-on", "site-a"))
        await store.put(
            user_id=user_id,
            value=_note("auto-off", "site-a", auto_retrieve=False),
        )

        results = await retrieve_relevant_memories(
            store=store,
            user_id=user_id,
            query="measured counts note",
            scope=RetrievalScope(kinds=DECLARED_KINDS, top_k=8),
        )
        names = {m.value.name for m in results}
        assert "auto-on" in names
        assert "auto-off" not in names, "auto_retrieve=False must be withheld"
