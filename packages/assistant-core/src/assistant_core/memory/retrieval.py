from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True)
class RetrievalScope:
    """What one turn reads from memory.

    ``kinds`` are ranked by similarity to the request. ``always_kinds`` are
    listed instead, for a kind whose value does not depend on the request,
    such as a standing preference. A kind named in both is listed once.
    ``keep`` is the caller's scope rule, such as the data host a memory
    belongs to; a caller that supplies none ranks every candidate. ``top_k``
    bounds the ranking and ``always_top_k`` the listing, so an answer holds at
    most the two added together.

    The five are one argument because the caller states all of them together.
    """

    kinds: Sequence[str]
    always_kinds: Sequence[str] = ()
    keep: Callable[[MemoryValue], bool] | None = None
    top_k: int = 8
    always_top_k: int = 8

    def admits(self, memory: MemoryValue) -> bool:
        if not memory.auto_retrieve:
            return False
        return self.keep is None or self.keep(memory)


def _recency_key(stored: StoredMemory) -> datetime:
    return stored.value.last_used_at or stored.value.created_at


async def _listed_memories(
    *,
    store: MemoryStore,
    user_id: UUID,
    scope: RetrievalScope,
) -> list[StoredMemory]:
    """The always-kinds the scope admits, newest first, inside their budget."""
    found: list[StoredMemory] = []
    for kind in dict.fromkeys(scope.always_kinds):
        listed = await store.list_all(
            user_id=user_id,
            kind=kind,
            limit=scope.always_top_k,
        )
        found.extend(stored for stored in listed if scope.admits(stored.value))
    found.sort(key=_recency_key, reverse=True)
    return found[: scope.always_top_k]


async def retrieve_relevant_memories(
    *,
    store: MemoryStore,
    user_id: UUID,
    query: str,
    scope: RetrievalScope,
) -> list[StoredMemory]:
    """The listed kinds, then the similarity ranking over the rest.

    A ranked namespace is queried for up to ``top_k // 2`` hits; candidates
    the scope admits are scored via :func:`hybrid_score` using the HNSW cosine
    similarity as the ``semantic`` signal. The answer is the newest
    ``always_top_k`` of the listed kinds followed by the global top ``top_k``,
    deduplicated by key, as :class:`StoredMemory` (carrying ``key`` +
    ``score`` for display); call ``.value`` for the bare
    :class:`MemoryValue`.
    """
    always = await _listed_memories(store=store, user_id=user_id, scope=scope)
    seen = {stored.key for stored in always}
    per_kind = max(1, scope.top_k // 2)
    all_hits: list[StoredMemory] = []
    for kind in scope.kinds:
        if kind in scope.always_kinds:
            continue
        hits = await store.semantic_search(
            user_id=user_id,
            kind=kind,
            query=query,
            top_k=per_kind,
        )
        all_hits.extend(
            stored
            for stored in hits
            if stored.key not in seen and scope.admits(stored.value)
        )
    ranked = rerank_by_hybrid_score(all_hits)[: scope.top_k]
    return always + ranked
