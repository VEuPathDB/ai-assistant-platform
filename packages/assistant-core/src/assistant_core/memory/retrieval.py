from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore, StoredMemory

SEMANTIC_WEIGHT = 0.7
RECENCY_WEIGHT = 0.2
PIN_WEIGHT = 0.1
RECENCY_HALF_LIFE_DAYS = 30.0


def rerank_by_hybrid_score(
    stored_hits: list[StoredMemory],
) -> list[StoredMemory]:
    """Sort candidates by :func:`hybrid_score`, highest first.

    Single source of truth — both :func:`retrieve_relevant_memories` (graph
    retrieval for ``pinned_user_memories``) and the LLM-callable
    ``search_memory`` tool use this to merge across-namespace results
    into a global ranking. The semantic input is each candidate's HNSW
    score clamped to ``[0, 1]`` per
    :func:`embedding.embed_text`'s L2-normalization invariant.
    """
    scored = [
        (
            hybrid_score(memory=s.value, semantic=_clamp_semantic(s.score)),
            s,
        )
        for s in stored_hits
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [s for _score, s in scored]


def _recency_boost(memory: MemoryValue) -> float:
    if memory.last_used_at is None:
        return 0.5
    delta = datetime.now(UTC) - memory.last_used_at
    days = max(delta.total_seconds() / 86400.0, 0.0)
    return math.exp(-days / RECENCY_HALF_LIFE_DAYS)


def _pin_boost(memory: MemoryValue) -> float:
    return 1.0 if "pinned" in memory.tags else 0.0


def hybrid_score(*, memory: MemoryValue, semantic: float) -> float:
    return (
        SEMANTIC_WEIGHT * semantic
        + RECENCY_WEIGHT * _recency_boost(memory)
        + PIN_WEIGHT * _pin_boost(memory)
    )


def _clamp_semantic(score: float | None) -> float:
    if score is None:
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


async def retrieve_relevant_memories(
    *,
    store: MemoryStore,
    user_id: UUID,
    query: str,
    site_id: str | None,
    kinds: Sequence[str],
    top_k: int = 8,
) -> list[StoredMemory]:
    """Search every auto-retrieve-enabled namespace, rerank by hybrid score.

    Each namespace is queried for up to ``top_k // 2`` hits; candidates are
    filtered by ``auto_retrieve`` + site compatibility, then scored via
    :func:`hybrid_score` using the HNSW cosine similarity as the
    ``semantic`` signal. Returns the global top ``top_k`` as
    :class:`StoredMemory` (carrying ``key`` + ``score`` for display) — call
    ``.value`` for the bare :class:`MemoryValue`.
    """
    per_kind = max(1, top_k // 2)
    all_hits: list[StoredMemory] = []
    for kind in kinds:
        hits = await store.semantic_search(
            user_id=user_id,
            kind=kind,
            query=query,
            top_k=per_kind,
        )
        for stored in hits:
            if not stored.value.auto_retrieve:
                continue
            if (
                site_id is not None
                and stored.value.site_id is not None
                and stored.value.site_id != site_id
            ):
                continue
            all_hits.append(stored)
    reranked = rerank_by_hybrid_score(all_hits)
    return reranked[:top_k]
