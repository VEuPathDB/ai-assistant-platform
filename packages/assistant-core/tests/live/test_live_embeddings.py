"""One real call against the embeddings API. Opt in with -m live_embeddings."""

from __future__ import annotations

import math
import os

import pytest

from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS
from assistant_core.embeddings.openai_embedder import OpenAIEmbedder
from assistant_core.platform.config import RuntimeSettings

pytestmark = pytest.mark.live_embeddings


async def test_the_api_answers_at_the_configured_width() -> None:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY is not set")
    embedder = OpenAIEmbedder(
        settings=RuntimeSettings(openai_api_key=key, embedding_backend="openai"),
    )
    vectors = await embedder.embed_documents(
        ["gametocyte development in Plasmodium falciparum", "a chocolate cake recipe"],
    )
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == EMBEDDING_DIMENSIONS
        assert math.isclose(sum(v * v for v in vector), 1.0, abs_tol=1e-3)
    assert vectors[0] != vectors[1]


async def test_the_api_ranks_a_related_text_above_an_unrelated_one() -> None:
    """The only place semantic ranking is asserted: it is the API's behaviour."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY is not set")
    embedder = OpenAIEmbedder(
        settings=RuntimeSettings(openai_api_key=key, embedding_backend="openai"),
    )
    query, relevant, irrelevant = await embedder.embed_documents(
        ["antimalarial drugs", "plasmodium drug targets", "cookie recipe"],
    )

    assert _cosine(query, relevant) > _cosine(query, irrelevant)


def _cosine(left: list[float], right: list[float]) -> float:
    """The API returns unit vectors, so the dot product is the cosine."""
    return sum(a * b for a, b in zip(left, right, strict=True))
