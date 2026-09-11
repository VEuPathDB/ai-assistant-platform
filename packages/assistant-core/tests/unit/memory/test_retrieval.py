from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from assistant_core.memory.retrieval import (
    hybrid_score,
    rerank_by_hybrid_score,
    retrieve_relevant_memories,
)
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import StoredMemory


def _m(
    tags: list[str],
    last_used_days_ago: float | None,
    *,
    name: str = "x",
) -> MemoryValue:
    last_used = (
        datetime.now(UTC) - timedelta(days=last_used_days_ago)
        if last_used_days_ago is not None
        else None
    )
    return MemoryValue(
        kind="note",
        name=name,
        summary="y",
        tags=tags,
        content={},
        created_at=datetime.now(UTC),
        last_used_at=last_used,
    )


def test_hybrid_score_combines_semantic_recency_pin() -> None:
    m = _m(tags=[], last_used_days_ago=0)
    score = hybrid_score(memory=m, semantic=1.0)
    # 0.7*1.0 + 0.2*exp(-0/30) + 0.1*0 = 0.70 + 0.20 + 0 = 0.90.
    assert score == pytest.approx(0.90, abs=1e-6)


def test_recency_decay() -> None:
    fresh = hybrid_score(memory=_m(tags=[], last_used_days_ago=0), semantic=0.5)
    stale = hybrid_score(memory=_m(tags=[], last_used_days_ago=90), semantic=0.5)
    # fresh = 0.7*0.5 + 0.2*exp(0)      = 0.35 + 0.20      = 0.55000
    # stale = 0.7*0.5 + 0.2*exp(-90/30) = 0.35 + 0.0099574 = 0.3599574
    assert fresh == pytest.approx(0.55, abs=1e-6)
    assert stale == pytest.approx(0.3599574, abs=1e-5)


def test_pinned_tag_boosts_score() -> None:
    unpinned = hybrid_score(memory=_m(tags=[], last_used_days_ago=30), semantic=0.5)
    pinned = hybrid_score(
        memory=_m(tags=["pinned"], last_used_days_ago=30), semantic=0.5
    )
    assert pinned > unpinned
    assert pinned - unpinned == pytest.approx(0.1, abs=0.01)


def test_rerank_recency_and_pin_override_raw_semantic() -> None:
    """A fresh+pinned hit must outrank a staler hit with higher raw semantic.

    semantic-only order is [stale, fresh] (0.9 > 0.5); the hybrid score
    flips it because recency+pin add 0.30 to ``fresh`` but only ~0.01 to
    ``stale``. Hand-computed:
      stale = 0.7*0.9 + 0.2*exp(-90/30) + 0   = 0.63 + 0.00996 = 0.63996
      fresh = 0.7*0.5 + 0.2*1.0       + 0.1*1 = 0.35 + 0.20 + 0.10 = 0.65000
    """
    stale = StoredMemory(
        key="stale",
        value=_m(tags=[], last_used_days_ago=90, name="stale"),
        score=0.9,
    )
    fresh = StoredMemory(
        key="fresh",
        value=_m(tags=["pinned"], last_used_days_ago=0, name="fresh"),
        score=0.5,
    )
    # Sanity: raw semantic would have ordered them the other way.
    assert (stale.score or 0.0) > (fresh.score or 0.0)

    ranked = rerank_by_hybrid_score([stale, fresh])
    assert [s.key for s in ranked] == ["fresh", "stale"]


def test_rerank_clamps_out_of_range_and_none_semantic() -> None:
    """``score`` outside [0,1] is clamped to 1.0; ``None`` (no HNSW hit) → 0.

    over:  0.7*min(1.5,1.0) + 0.2*1.0 = 0.90 (clamp caps semantic at 1.0)
    none:  0.7*0.0          + 0.2*1.0 = 0.20
    """
    over = StoredMemory(
        key="over",
        value=_m(tags=[], last_used_days_ago=0, name="over"),
        score=1.5,
    )
    none_hit = StoredMemory(
        key="none",
        value=_m(tags=[], last_used_days_ago=0, name="none"),
        score=None,
    )
    ranked = rerank_by_hybrid_score([none_hit, over])
    assert [s.key for s in ranked] == ["over", "none"]
    over_score = hybrid_score(memory=over.value, semantic=1.0)
    assert over_score == pytest.approx(0.90, abs=1e-9)


class _HitsByKind:
    """A store stand-in that answers each kind with the hits it was given."""

    def __init__(self, hits: dict[str, list[StoredMemory]]) -> None:
        self.hits = hits

    async def semantic_search(
        self,
        *,
        user_id: UUID,
        kind: str,
        query: str,
        top_k: int = 8,
    ) -> list[StoredMemory]:
        del user_id, query, top_k
        return self.hits.get(kind, [])


def _hit(key: str, *, site_id: str | None, auto_retrieve: bool = True) -> StoredMemory:
    value = MemoryValue(
        kind="note",
        name=key,
        summary="y",
        tags=[],
        site_id=site_id,
        content={},
        auto_retrieve=auto_retrieve,
        created_at=datetime.now(UTC),
    )
    return StoredMemory(key=key, value=value, score=0.5)


@pytest.mark.asyncio
async def test_retrieval_keeps_every_candidate_the_host_allows() -> None:
    """The runtime scores and ranks; which memories are in scope is the host's."""
    store = _HitsByKind(
        {"note": [_hit("here", site_id="a"), _hit("elsewhere", site_id="b")]}
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        kinds=("note",),
        keep=lambda memory: memory.site_id == "a",
    )

    assert [hit.key for hit in ranked] == ["here"]


@pytest.mark.asyncio
async def test_retrieval_without_a_predicate_ranks_every_candidate() -> None:
    store = _HitsByKind(
        {"note": [_hit("here", site_id="a"), _hit("elsewhere", site_id="b")]}
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        kinds=("note",),
    )

    assert {hit.key for hit in ranked} == {"here", "elsewhere"}


@pytest.mark.asyncio
async def test_retrieval_withholds_what_the_writer_marked_not_auto_retrieve() -> None:
    store = _HitsByKind({"note": [_hit("held", site_id=None, auto_retrieve=False)]})

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        kinds=("note",),
    )

    assert ranked == []
