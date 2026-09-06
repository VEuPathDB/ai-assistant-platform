from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from assistant_core.embeddings.embedder import (
    EMBEDDING_DIMENSIONS,
    EmbeddingUnavailableError,
)
from assistant_core.memory import lifespan
from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore


def _axis(position: int) -> list[float]:
    """A unit vector on one axis, so two texts are orthogonal or identical."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[position] = 1.0
    return vector


@pytest.mark.asyncio
async def test_memory_store_put_and_get(
    db_cleaner: None, patch_app_db_engine: None
) -> None:
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()
    async with lifespan_memory_store(database_url) as raw_store:
        store = MemoryStore(store=raw_store)
        value = MemoryValue(
            kind="gene_set",
            name="test_set",
            summary="a description",
            tags=["tag"],
            content={"gene_ids": ["PF3D7_0102500"]},
            created_at=datetime.now(UTC),
        )
        stored_key = await store.put(user_id=user_id, value=value)

        listed = await store.list_all(user_id=user_id, kind="gene_set")
        assert len(listed) == 1
        assert listed[0].key == stored_key
        assert listed[0].value.name == "test_set"


@pytest.mark.asyncio
async def test_memory_store_search_returns_the_nearest_vector_first(
    db_cleaner: None, patch_app_db_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store ranks by the vectors it is given, best first."""
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()

    async def keyed_embed(texts: Sequence[str]) -> list[list[float]]:
        return [_axis(0 if "malaria" in text else 1) for text in texts]

    monkeypatch.setattr(lifespan, "embed_text", keyed_embed)

    async with lifespan_memory_store(database_url) as raw_store:
        store = MemoryStore(store=raw_store)
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="malaria_drug_targets",
                summary="plasmodium falciparum validated drug targets phase 2",
                tags=["malaria", "drug"],
                content={"fact": "verified"},
                created_at=datetime.now(UTC),
            ),
        )
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="cookie_recipe",
                summary="chocolate chip cookies with brown butter",
                tags=["recipe"],
                content={"fact": "other"},
                created_at=datetime.now(UTC),
            ),
        )

        hits = await store.semantic_search(
            user_id=user_id,
            kind="knowledge",
            query="malaria drug targets",
            top_k=2,
        )
        assert len(hits) == 2
        assert hits[0].value.name == "malaria_drug_targets"
        assert hits[0].score is not None
        assert hits[1].score is not None
        assert hits[0].score > hits[1].score


@pytest.mark.asyncio
async def test_store_embeds_the_memory_text_and_the_raw_query(
    db_cleaner: None, patch_app_db_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A put embeds the combined memory text; a search embeds the query verbatim.

    The LangGraph Postgres store routes both paths through
    ``aembed_documents``, so a capturing embed records exactly what each path
    asks for.
    """
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()
    embedded_texts: list[str] = []

    async def capturing_embed(texts: Sequence[str]) -> list[list[float]]:
        embedded_texts.extend(texts)
        unit = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        return [list(unit) for _ in texts]

    monkeypatch.setattr(lifespan, "embed_text", capturing_embed)

    async with lifespan_memory_store(database_url) as raw_store:
        store = MemoryStore(store=raw_store)
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="surface_antigen_set",
                summary="merozoite surface proteins",
                tags=["malaria"],
                content={"fact": "verified"},
                created_at=datetime.now(UTC),
            ),
        )
        await store.semantic_search(
            user_id=user_id,
            kind="knowledge",
            query="vaccine targets",
            top_k=1,
        )

    assert any("surface_antigen_set" in text for text in embedded_texts)
    assert "vaccine targets" in embedded_texts


class _SwitchableEmbed:
    """A real embed the store captures at open, which can start refusing."""

    def __init__(self) -> None:
        self.refusing = False

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if self.refusing:
            raise EmbeddingUnavailableError(batch_size=len(texts), cause="no route")
        return [_axis(0) for _ in texts]


@pytest.mark.asyncio
async def test_a_search_with_no_embedding_api_returns_nothing(
    db_cleaner: None, patch_app_db_engine: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable embedding API costs the turn its memories, not the turn.

    The store captures its embed when it opens, so the refusal is installed
    before that and switched on once a memory is stored.
    """
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    user_id = uuid4()
    embed = _SwitchableEmbed()
    monkeypatch.setattr(lifespan, "embed_text", embed)

    async with lifespan_memory_store(database_url) as raw_store:
        store = MemoryStore(store=raw_store)
        await store.put(
            user_id=user_id,
            value=MemoryValue(
                kind="knowledge",
                name="reachable_memory",
                summary="stored while the API answered",
                tags=[],
                content={},
                created_at=datetime.now(UTC),
            ),
        )
        # The memory is there while the API answers.
        assert (
            len(
                await store.semantic_search(
                    user_id=user_id,
                    kind="knowledge",
                    query="anything",
                    top_k=3,
                )
            )
            == 1
        )

        embed.refusing = True
        with capture_logs() as logs:
            hits = await store.semantic_search(
                user_id=user_id,
                kind="knowledge",
                query="anything",
                top_k=3,
            )

    assert hits == []
    assert [entry["event"] for entry in logs] == ["Memory search returned nothing"]
    assert "no route" in logs[0]["error"]
