"""The batching, concurrency and failure behaviour of the OpenAI embedder."""

from __future__ import annotations

import asyncio
import math

import pytest
from openai.types.create_embedding_response import CreateEmbeddingResponse

from assistant_core.embeddings.embedder import (
    EMBEDDING_DIMENSIONS,
    EmbeddingUnavailableError,
)
from assistant_core.embeddings.openai_embedder import OpenAIEmbedder
from assistant_core.platform.config import RuntimeSettings


class _RecordingApi:
    """An embed call that records every request it is given."""

    def __init__(self, *, delay: float = 0.0, failures: int = 0) -> None:
        self.batches: list[list[str]] = []
        self.dimensions: list[int] = []
        self.models: list[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0
        self._delay = delay
        self._failures = failures
        self._attempts = 0

    async def __call__(
        self,
        texts: list[str],
        model: str,
        dimensions: int,
    ) -> CreateEmbeddingResponse:
        self._attempts += 1
        if self._attempts <= self._failures:
            msg = "upstream refused"
            raise RuntimeError(msg)
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            self.batches.append(list(texts))
            self.dimensions.append(dimensions)
            self.models.append(model)
            return CreateEmbeddingResponse.model_validate(
                {
                    "object": "list",
                    "model": model,
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                    "data": [
                        {
                            "object": "embedding",
                            "index": position,
                            "embedding": _vector_for(text, dimensions),
                        }
                        for position, text in enumerate(texts)
                    ],
                },
            )
        finally:
            self.in_flight -= 1


def _vector_for(text: str, dimensions: int) -> list[float]:
    raw = [float(len(text) + position) for position in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in raw))
    return [value / norm for value in raw]


def _embedder(
    api: _RecordingApi,
    **overrides: object,
) -> OpenAIEmbedder:
    settings = RuntimeSettings(openai_api_key="test-key", **overrides)
    return OpenAIEmbedder(settings=settings, embed_call=api)


async def test_batches_by_item_count() -> None:
    api = _RecordingApi()
    texts = [f"text {index}" for index in range(1000)]
    await _embedder(api).embed_documents(texts)
    assert len(api.batches) == math.ceil(1000 / 256)
    assert [len(batch) for batch in api.batches] == [256, 256, 256, 232]


async def test_batches_by_character_budget() -> None:
    api = _RecordingApi()
    texts = ["x" * 2000 for _ in range(200)]
    await _embedder(api).embed_documents(texts)
    assert all(sum(len(text) for text in batch) <= 200_000 for batch in api.batches)
    assert len(api.batches) == 2


async def test_preserves_input_order_across_concurrent_batches() -> None:
    api = _RecordingApi(delay=0.01)
    texts = [f"{'y' * index}" for index in range(1, 600)]
    vectors = await _embedder(api).embed_documents(texts)
    assert vectors == [_vector_for(text, EMBEDDING_DIMENSIONS) for text in texts]


async def test_holds_at_most_the_configured_requests_in_flight() -> None:
    api = _RecordingApi(delay=0.02)
    texts = [f"text {index}" for index in range(256 * 20)]
    await _embedder(api).embed_documents(texts)
    assert api.peak_in_flight <= 8
    assert api.peak_in_flight > 1


async def test_cuts_every_input_at_the_character_limit() -> None:
    api = _RecordingApi()
    await _embedder(api).embed_documents(["z" * 5000])
    assert api.batches == [["z" * 2000]]


async def test_query_is_cut_at_the_same_limit() -> None:
    api = _RecordingApi()
    vector = await _embedder(api).embed_query("q" * 5000)
    assert api.batches == [["q" * 2000]]
    assert len(vector) == EMBEDDING_DIMENSIONS


async def test_passes_the_configured_model() -> None:
    api = _RecordingApi()
    await _embedder(api, embedding_model="text-embedding-3-small").embed_documents(
        ["one"],
    )
    assert api.models == ["text-embedding-3-small"]


async def test_the_width_is_the_constant_the_column_is_declared_at() -> None:
    """A setting could not widen the column, so a setting cannot name the width."""
    api = _RecordingApi()
    await _embedder(api, embedding_dimensions=256).embed_documents(["one"])
    assert api.dimensions == [EMBEDDING_DIMENSIONS]
    assert "embedding_dimensions" not in RuntimeSettings.model_fields


async def test_empty_input_makes_no_request() -> None:
    api = _RecordingApi()
    assert await _embedder(api).embed_documents([]) == []
    assert api.batches == []


async def test_blank_text_is_sent_as_a_single_space() -> None:
    api = _RecordingApi()
    await _embedder(api).embed_documents(["", "   "])
    assert api.batches == [[" ", " "]]


async def test_a_refused_batch_raises_embedding_unavailable() -> None:
    api = _RecordingApi(failures=1)
    with pytest.raises(EmbeddingUnavailableError) as raised:
        await _embedder(api).embed_documents(["one", "two"])
    assert "2" in str(raised.value)
    assert "upstream refused" in str(raised.value)
