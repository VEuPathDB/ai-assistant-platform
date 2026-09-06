"""A deterministic offline embedder, for suites that have no API key."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS

_SEED_BYTES = 4


class FakeEmbedder:
    """Vectors seeded from the text, so one text always gives one vector."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [_vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls.append([text])
        return _vector(text)


def _vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    seed = int.from_bytes(digest[:_SEED_BYTES], "big")
    raw = np.random.RandomState(seed).normal(size=EMBEDDING_DIMENSIONS)
    return [float(value) for value in raw / np.linalg.norm(raw)]
