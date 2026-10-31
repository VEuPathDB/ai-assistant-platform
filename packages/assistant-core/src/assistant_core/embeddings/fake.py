"""A deterministic offline embedder, for suites that have no API key."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from assistant_core.embeddings.embedder import EMBEDDING_DIMENSIONS

_SEED_BYTES = 4
_WORD = re.compile(r"\w+")


class FakeEmbedder:
    """Vectors summed from the words of the text, so one text always gives one
    vector and texts that share words lie close."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [_vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls.append([text])
        return _vector(text)


def _seeded(token: str) -> np.ndarray:
    digest = hashlib.sha256(token.encode()).digest()
    seed = int.from_bytes(digest[:_SEED_BYTES], "big")
    return np.random.RandomState(seed).normal(size=EMBEDDING_DIMENSIONS)


def _vector(text: str) -> list[float]:
    words = sorted(set(_WORD.findall(text.casefold())))
    raw = np.sum([_seeded(word) for word in words], axis=0) if words else _seeded(text)
    return [float(value) for value in raw / np.linalg.norm(raw)]
