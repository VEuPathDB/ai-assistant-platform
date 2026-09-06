from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS
from assistant_core.memory.embedding import embed_text, format_embedded_string
from assistant_core.memory.schemas import MemoryValue


def test_embedding_dimensions_are_1024() -> None:
    assert EMBEDDING_DIMENSIONS == 1024


@pytest.mark.asyncio
async def test_embed_text_returns_one_vector_per_text(
    use_fake_embedder: None,
) -> None:
    del use_fake_embedder
    vectors = await embed_text(["hello", "world", "foo bar"])
    assert len(vectors) == 3
    for vector in vectors:
        assert len(vector) == EMBEDDING_DIMENSIONS
        assert all(isinstance(value, float) for value in vector)


@pytest.mark.asyncio
async def test_embed_text_returns_unit_vectors(use_fake_embedder: None) -> None:
    """``retrieval._clamp_semantic`` reads a cosine, so the vectors are unit."""
    del use_fake_embedder
    vectors = await embed_text(["norm check"])
    norm_sq = sum(value * value for value in vectors[0])
    assert math.isclose(norm_sq, 1.0, rel_tol=1e-9)


def test_format_embedded_string_carries_the_semantic_payload() -> None:
    value = MemoryValue(
        kind="gene_set",
        name="vaccine_antigens",
        summary="surface-exposed blood-stage antigens",
        tags=["malaria", "vaccine"],
        content={},
        created_at=datetime.now(UTC),
    )
    text = format_embedded_string(value)
    assert text == (
        "gene_set :: vaccine_antigens :: malaria, vaccine :: "
        "surface-exposed blood-stage antigens"
    )
