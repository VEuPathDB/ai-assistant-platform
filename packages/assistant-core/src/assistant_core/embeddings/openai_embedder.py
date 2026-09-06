"""The OpenAI embeddings API, batched and run in parallel."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from openai import AsyncOpenAI, OpenAIError
from openai.types.create_embedding_response import CreateEmbeddingResponse
from pydantic import BaseModel, ConfigDict

from assistant_core.embeddings.embedder import (
    EMBEDDING_DIMENSIONS,
    EmbeddingUnavailableError,
)
from assistant_core.platform.config import RuntimeSettings

# The API reads at most this many characters over all inputs of one request.
REQUEST_CHAR_BUDGET = 200_000

_REQUEST_TIMEOUT_SECONDS = 60.0
_MAX_RETRIES = 5

# One request: the texts, the model, and the width to answer at.
type EmbedCall = Callable[
    [list[str], str, int],
    Awaitable[CreateEmbeddingResponse],
]


def openai_embed_call(client: AsyncOpenAI) -> EmbedCall:
    """The one call this module makes against the embeddings API."""

    async def call(
        texts: list[str],
        model: str,
        dimensions: int,
    ) -> CreateEmbeddingResponse:
        return await client.embeddings.create(
            input=texts,
            model=model,
            dimensions=dimensions,
        )

    return call


class _EmbeddingRow(BaseModel):
    """One vector of a response, and the input position it answers."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    index: int
    embedding: list[float]


class EmbeddingBatch(BaseModel):
    """The vectors of one request, read back in input order."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    data: list[_EmbeddingRow]

    @property
    def vectors(self) -> list[list[float]]:
        return [row.embedding for row in sorted(self.data, key=lambda r: r.index)]


class OpenAIEmbedder:
    """Embeds text through the OpenAI embeddings API."""

    def __init__(
        self,
        *,
        settings: RuntimeSettings,
        embed_call: EmbedCall | None = None,
    ) -> None:
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size
        self._char_limit = settings.embedding_input_char_limit
        self._gate = asyncio.Semaphore(settings.embedding_request_concurrency)
        self._call = embed_call or openai_embed_call(
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                max_retries=_MAX_RETRIES,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            ),
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the order given."""
        prepared = [self._prepare(text) for text in texts]
        if not prepared:
            return []
        batches = self._batches(prepared)
        results = await asyncio.gather(*(self._embed_batch(b) for b in batches))
        return [vector for batch in results for vector in batch]

    async def embed_query(self, text: str) -> list[float]:
        """One vector for a query."""
        return (await self.embed_documents([text]))[0]

    def _prepare(self, text: str) -> str:
        """The text as the API reads it: cut, and never empty."""
        cut = text[: self._char_limit]
        return cut if cut.strip() else " "

    def _batches(self, texts: list[str]) -> list[list[str]]:
        """Group the inputs under the item count and the character budget."""
        batches: list[list[str]] = []
        current: list[str] = []
        current_chars = 0
        for text in texts:
            over_count = len(current) >= self._batch_size
            over_chars = current and current_chars + len(text) > REQUEST_CHAR_BUDGET
            if over_count or over_chars:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(text)
            current_chars += len(text)
        if current:
            batches.append(current)
        return batches

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with self._gate:
            try:
                response = await self._call(texts, self._model, EMBEDDING_DIMENSIONS)
            except (OpenAIError, OSError, RuntimeError) as exc:
                raise EmbeddingUnavailableError(
                    batch_size=len(texts),
                    cause=str(exc),
                ) from exc
        return EmbeddingBatch.model_validate(response).vectors
