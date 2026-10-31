"""The deterministic embedder the offline suites select."""

from __future__ import annotations

import asyncio
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


async def test_a_title_finds_the_text_that_holds_it() -> None:
    embedder = FakeEmbedder()
    title = "5 asexual and sexual stage transcriptomes"
    named = f"{title} RNA-Seq of the asexual blood stages, gametocytes and ookinetes"
    texts = [
        *(f"Study {n} of heat shock in mutant line {n}" for n in range(60)),
        named,
        *(f"Infection time course {n} in cell line {n}" for n in range(60)),
    ]
    query = await embedder.embed_query(title)
    scores = [
        sum(a * b for a, b in zip(query, vector, strict=True))
        for vector in await embedder.embed_documents(texts)
    ]
    assert texts[scores.index(max(scores))] == named


async def test_a_large_batch_leaves_the_event_loop_free() -> None:
    texts = [
        " ".join(f"word{(n * 31 + k) % 5000}" for k in range(80)) for n in range(1500)
    ]
    embedding = asyncio.create_task(FakeEmbedder().embed_documents(texts))
    ticks = 0
    while not embedding.done():
        ticks += 1
        await asyncio.sleep(0)

    assert ticks > 1
    assert len(await embedding) == len(texts)
