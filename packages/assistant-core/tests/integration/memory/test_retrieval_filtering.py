"""Cross-namespace retrieval must respect site scope and the auto_retrieve flag.

For a pathogen researcher, surfacing a memory from the wrong organism site is a
data-correctness bug — a ``plasmodb`` (malaria) query must never return a
``toxodb`` (toxoplasma) memory. Site-agnostic memories (``site_id is None``,
e.g. knowledge) stay visible everywhere, and ``auto_retrieve=False`` memories
are withheld from the graph-time retrieval entirely.

These run against the real pgvector HNSW store + embeddings (only the LLM is
ever mocked), so they also cover the ``semantic_search`` → filter → rerank
merge across the namespaces.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.memory.retrieval import retrieve_relevant_memories
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore

# The kinds an assistant declares; this suite uses the four the store ships with.
DECLARED_KINDS: tuple[str, ...] = ("gene_set", "strategy", "preference", "knowledge")


def _gene_set(
    name: str, site_id: str | None, *, auto_retrieve: bool = True
) -> MemoryValue:
    return MemoryValue(
        kind="gene_set",
        name=name,
        summary=f"kinase gene set {name} on {site_id}",
        tags=[site_id] if site_id else [],
        site_id=site_id,
        content={"gene_set_id": name},
        auto_retrieve=auto_retrieve,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_retrieval_excludes_other_site_keeps_agnostic(
    db_cleaner: None,
    patch_app_db_engine: None,
) -> None:
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()

    async with lifespan_memory_store(database_url) as raw:
        store = MemoryStore(store=raw)
        await store.put(user_id=user_id, value=_gene_set("plasmo-set", "plasmodb"))
        await store.put(user_id=user_id, value=_gene_set("toxo-set", "toxodb"))
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="kinase-fact",
                summary="kinases phosphorylate substrates",
                tags=[],
                site_id=None,
                content={"fact": "kinase"},
                created_at=datetime.now(UTC),
            ),
        )

        results = await retrieve_relevant_memories(
            store=store,
            user_id=user_id,
            query="kinase gene set",
            site_id="plasmodb",
            kinds=DECLARED_KINDS,
            top_k=8,
        )
        names = {m.value.name for m in results}
        assert "plasmo-set" in names, "same-site memory must be retrieved"
        assert "kinase-fact" in names, "site-agnostic memory must be retrieved"
        assert "toxo-set" not in names, "other-site memory must be filtered out"


@pytest.mark.asyncio
async def test_retrieval_withholds_auto_retrieve_false(
    db_cleaner: None,
    patch_app_db_engine: None,
) -> None:
    """A memory flagged ``auto_retrieve=False`` is excluded from graph-time
    retrieval even when it is the strongest same-site semantic match.
    """
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()

    async with lifespan_memory_store(database_url) as raw:
        store = MemoryStore(store=raw)
        await store.put(
            user_id=user_id,
            value=_gene_set("auto-on", "plasmodb"),
        )
        await store.put(
            user_id=user_id,
            value=_gene_set("auto-off", "plasmodb", auto_retrieve=False),
        )

        results = await retrieve_relevant_memories(
            store=store,
            user_id=user_id,
            query="kinase gene set",
            site_id="plasmodb",
            kinds=DECLARED_KINDS,
            top_k=8,
        )
        names = {m.value.name for m in results}
        assert "auto-on" in names
        assert "auto-off" not in names, "auto_retrieve=False must be withheld"
