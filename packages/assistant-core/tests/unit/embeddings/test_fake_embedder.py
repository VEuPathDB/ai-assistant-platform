"""The deterministic embedder the offline suites select."""

from __future__ import annotations

import math

from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS, get_embedder
from assistant_core.embeddings.fake import FakeEmbedder


async def test_vectors_are_deterministic_and_unit_normalized() -> None:
    embedder = FakeEmbedder()
    first = await embedder.embed_documents(["heat shock"])
    second = await embedder.embed_documents(["heat shock"])
    assert first == second
    assert len(first[0]) == EMBEDDING_DIMENSIONS
    norm = math.sqrt(sum(value * value for value in first[0]))
    assert math.isclose(norm, 1.0, rel_tol=1e-9)


async def test_different_texts_give_different_vectors() -> None:
    embedder = FakeEmbedder()
    vectors = await embedder.embed_documents(["alpha", "beta"])
    assert vectors[0] != vectors[1]


async def test_every_call_is_recorded() -> None:
    embedder = FakeEmbedder()
    await embedder.embed_documents(["one", "two"])
    await embedder.embed_query("three")
    assert embedder.calls == [["one", "two"], ["three"]]


async def test_the_backend_setting_selects_the_fake(use_fake_embedder: None) -> None:
    del use_fake_embedder
    assert isinstance(get_embedder(), FakeEmbedder)
