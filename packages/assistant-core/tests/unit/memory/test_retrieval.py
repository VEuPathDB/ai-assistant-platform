from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langgraph.store.base import Result, SearchItem, SearchOp
from langgraph.store.base.batch import AsyncBatchedBaseStore

from assistant_core.embeddings.embedder import EmbeddingUnavailableError
from assistant_core.memory.retrieval import (
    RetrievalScope,
    hybrid_score,
    rerank_by_hybrid_score,
    retrieve_relevant_memories,
)
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore, StoredMemory


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

    async def list_all(
        self,
        *,
        user_id: UUID,
        kind: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredMemory]:
        del user_id
        return self.hits.get(kind, [])[offset : offset + limit]


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
        scope=RetrievalScope(
            kinds=("note",),
            keep=lambda memory: memory.site_id == "a",
        ),
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
        scope=RetrievalScope(kinds=("note",)),
    )

    assert {hit.key for hit in ranked} == {"here", "elsewhere"}


@pytest.mark.asyncio
async def test_retrieval_withholds_what_the_writer_marked_not_auto_retrieve() -> None:
    store = _HitsByKind({"note": [_hit("held", site_id=None, auto_retrieve=False)]})

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(kinds=("note",)),
    )

    assert ranked == []


def _kind_hit(
    key: str,
    *,
    kind: str,
    score: float,
    last_used_days_ago: float = 1.0,
    auto_retrieve: bool = True,
) -> StoredMemory:
    value = MemoryValue(
        kind=kind,
        name=key,
        summary="y",
        tags=[],
        content={},
        auto_retrieve=auto_retrieve,
        created_at=datetime.now(UTC),
        last_used_at=datetime.now(UTC) - timedelta(days=last_used_days_ago),
    )
    return StoredMemory(key=key, value=value, score=score)


def _one_preference_among_twelve_cases() -> _HitsByKind:
    return _HitsByKind(
        {
            "preference": [_kind_hit("pref", kind="preference", score=0.1)],
            "case": [_kind_hit(f"case{n}", kind="case", score=0.9) for n in range(12)],
        }
    )


@pytest.mark.asyncio
async def test_a_listed_kind_comes_before_the_ranking() -> None:
    ranked = await retrieve_relevant_memories(
        store=_one_preference_among_twelve_cases(),
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(
            kinds=("preference", "case"),
            always_kinds=("preference",),
        ),
    )

    assert ranked[0].key == "pref"
    assert [hit.key for hit in ranked].count("pref") == 1


@pytest.mark.asyncio
async def test_without_an_always_kind_the_weak_preference_never_ranks() -> None:
    ranked = await retrieve_relevant_memories(
        store=_one_preference_among_twelve_cases(),
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(kinds=("preference", "case")),
    )

    assert "pref" not in [hit.key for hit in ranked]


@pytest.mark.asyncio
async def test_a_listed_kind_does_not_crowd_out_the_ranking() -> None:
    ranked = await retrieve_relevant_memories(
        store=_one_preference_among_twelve_cases(),
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(
            kinds=("preference", "case"),
            always_kinds=("preference",),
        ),
    )

    assert len(ranked) == 9
    assert len([hit for hit in ranked if hit.value.kind == "case"]) == 8


@pytest.mark.asyncio
async def test_the_kinds_read_in_full_come_newest_first() -> None:
    store = _HitsByKind(
        {
            "preference": [
                _kind_hit("older", kind="preference", score=0.1, last_used_days_ago=9),
                _kind_hit("newer", kind="preference", score=0.1, last_used_days_ago=1),
            ]
        }
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(kinds=(), always_kinds=("preference",)),
    )

    assert [hit.key for hit in ranked] == ["newer", "older"]


@pytest.mark.asyncio
async def test_a_listed_kind_still_answers_to_the_hosts_scope() -> None:
    store = _HitsByKind(
        {
            "preference": [
                _kind_hit("held", kind="preference", score=0.1, auto_retrieve=False),
                _kind_hit("shown", kind="preference", score=0.1),
            ]
        }
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(
            kinds=(),
            always_kinds=("preference",),
            keep=lambda memory: memory.name == "shown",
        ),
    )

    assert [hit.key for hit in ranked] == ["shown"]


@pytest.mark.asyncio
async def test_a_listed_kind_stops_at_its_budget() -> None:
    store = _HitsByKind(
        {
            "preference": [
                _kind_hit(f"pref{n}", kind="preference", score=0.1) for n in range(12)
            ]
        }
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(
            kinds=(),
            always_kinds=("preference",),
            always_top_k=3,
        ),
    )

    assert len(ranked) == 3


@pytest.mark.asyncio
async def test_a_kind_named_twice_is_listed_once() -> None:
    store = _HitsByKind({"preference": [_kind_hit("p1", kind="preference", score=0.1)]})

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(kinds=(), always_kinds=("preference", "preference")),
    )

    assert [hit.key for hit in ranked] == ["p1"]


class _SearchError(RuntimeError):
    """What one kind's search raises in the failure test below."""


class _BarrierStore:
    """A store stand-in whose reads answer only once all of them are in flight."""

    def __init__(self, *, hits: dict[str, list[StoredMemory]], reads: int) -> None:
        self.hits = hits
        self.reads = reads
        self.in_flight = 0
        self.peak_in_flight = 0
        self.all_in_flight = asyncio.Event()

    async def _arrive(self, kind: str) -> list[StoredMemory]:
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        if self.in_flight >= self.reads:
            self.all_in_flight.set()
        await asyncio.wait_for(self.all_in_flight.wait(), timeout=2.0)
        self.in_flight -= 1
        return self.hits.get(kind, [])

    async def semantic_search(
        self,
        *,
        user_id: UUID,
        kind: str,
        query: str,
        top_k: int = 8,
    ) -> list[StoredMemory]:
        del user_id, query, top_k
        return await self._arrive(kind)

    async def list_all(
        self,
        *,
        user_id: UUID,
        kind: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredMemory]:
        del user_id, limit, offset
        return await self._arrive(kind)


class _OrderedStore:
    """A store stand-in that records each read and how many of them run together."""

    def __init__(self, *, hits: dict[str, list[StoredMemory]]) -> None:
        self.hits = hits
        self.in_flight = 0
        self.peak_in_flight = 0
        self.reads: list[str] = []

    async def _read(self, label: str, kind: str) -> list[StoredMemory]:
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        self.reads.append(label)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return self.hits.get(kind, [])

    async def semantic_search(
        self,
        *,
        user_id: UUID,
        kind: str,
        query: str,
        top_k: int = 8,
    ) -> list[StoredMemory]:
        del user_id, query, top_k
        return await self._read(f"search:{kind}", kind)

    async def list_all(
        self,
        *,
        user_id: UUID,
        kind: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredMemory]:
        del user_id, limit, offset
        return await self._read(f"list:{kind}", kind)


class _FailingKind:
    """A store stand-in that raises for one kind and answers for the rest."""

    def __init__(self, *, failing_kind: str, hits: dict[str, list[StoredMemory]]):
        self.failing_kind = failing_kind
        self.hits = hits
        self.searched: list[str] = []

    async def semantic_search(
        self,
        *,
        user_id: UUID,
        kind: str,
        query: str,
        top_k: int = 8,
    ) -> list[StoredMemory]:
        del user_id, query, top_k
        self.searched.append(kind)
        if kind == self.failing_kind:
            raise _SearchError(kind)
        return self.hits.get(kind, [])

    async def list_all(
        self,
        *,
        user_id: UUID,
        kind: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredMemory]:
        del user_id, offset
        return self.hits.get(kind, [])[:limit]


async def _sequentially(
    *,
    store: _HitsByKind,
    user_id: UUID,
    query: str,
    scope: RetrievalScope,
) -> list[StoredMemory]:
    """One read after another, the shape the concurrent answer must match."""
    always: list[StoredMemory] = []
    for kind in dict.fromkeys(scope.always_kinds):
        listed = await store.list_all(
            user_id=user_id, kind=kind, limit=scope.always_top_k
        )
        always.extend(stored for stored in listed if scope.admits(stored.value))
    always.sort(
        key=lambda stored: stored.value.last_used_at or stored.value.created_at,
        reverse=True,
    )
    always = always[: scope.always_top_k]
    seen = {stored.key for stored in always}
    all_hits: list[StoredMemory] = []
    for kind in scope.kinds:
        if kind in scope.always_kinds:
            continue
        hits = await store.semantic_search(
            user_id=user_id,
            kind=kind,
            query=query,
            top_k=max(1, scope.top_k // 2),
        )
        all_hits.extend(
            stored
            for stored in hits
            if stored.key not in seen and scope.admits(stored.value)
        )
    return always + rerank_by_hybrid_score(all_hits)[: scope.top_k]


def _mixed_store() -> _HitsByKind:
    return _HitsByKind(
        {
            "preference": [
                _kind_hit(
                    "pref-old", kind="preference", score=0.1, last_used_days_ago=9
                ),
                _kind_hit("pref-new", kind="preference", score=0.1),
                _kind_hit(
                    "pref-held",
                    kind="preference",
                    score=0.1,
                    auto_retrieve=False,
                ),
            ],
            "case": [
                _kind_hit(
                    f"case{n}",
                    kind="case",
                    score=0.90 - n / 100,
                    last_used_days_ago=n + 1,
                )
                for n in range(6)
            ],
            "strategy": [
                _kind_hit("strat-a", kind="strategy", score=0.55),
                _kind_hit(
                    "strat-held", kind="strategy", score=0.54, auto_retrieve=False
                ),
            ],
            "knowledge": [_kind_hit("know-a", kind="knowledge", score=0.33)],
            "gene_set_note": [_kind_hit("note-a", kind="gene_set_note", score=0.22)],
        }
    )


@pytest.mark.asyncio
async def test_the_concurrent_answer_matches_the_sequential_one() -> None:
    """Same keys, same order, same scores as one read after another."""
    scope = RetrievalScope(
        kinds=("case", "strategy", "knowledge", "gene_set_note"),
        always_kinds=("preference",),
        always_top_k=2,
        top_k=6,
    )
    user_id = uuid4()

    concurrent = await retrieve_relevant_memories(
        store=_mixed_store(), user_id=user_id, query="q", scope=scope
    )
    sequential = await _sequentially(
        store=_mixed_store(), user_id=user_id, query="q", scope=scope
    )

    assert [(hit.key, hit.score) for hit in concurrent] == [
        (hit.key, hit.score) for hit in sequential
    ]


@pytest.mark.asyncio
async def test_the_ranked_kinds_are_searched_at_once() -> None:
    kinds = ("case", "strategy", "knowledge", "gene_set_note")
    store = _BarrierStore(
        hits={kind: [_kind_hit(kind, kind=kind, score=0.5)] for kind in kinds},
        reads=len(kinds),
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(kinds=kinds),
    )

    assert store.peak_in_flight == len(kinds)
    assert {hit.key for hit in ranked} == set(kinds)


@pytest.mark.asyncio
async def test_a_listed_kind_is_read_before_the_searches() -> None:
    """The listed read runs alone, ahead of the searches that run together."""
    store = _OrderedStore(
        hits={
            "preference": [_kind_hit("pref", kind="preference", score=0.1)],
            "case": [_kind_hit("case", kind="case", score=0.9)],
            "strategy": [_kind_hit("strat", kind="strategy", score=0.8)],
        }
    )

    ranked = await retrieve_relevant_memories(
        store=store,
        user_id=uuid4(),
        query="q",
        scope=RetrievalScope(
            kinds=("case", "strategy"),
            always_kinds=("preference",),
        ),
    )

    assert store.reads == ["list:preference", "search:case", "search:strategy"]
    assert store.peak_in_flight == 2
    assert [hit.key for hit in ranked] == ["pref", "case", "strat"]


@pytest.mark.asyncio
async def test_a_kind_whose_search_raises_fails_the_retrieval() -> None:
    """One failed kind fails the turn's retrieval; a partial ranking is never served."""
    store = _FailingKind(
        failing_kind="strategy",
        hits={"case": [_kind_hit("case", kind="case", score=0.9)]},
    )

    with pytest.raises(_SearchError):
        await retrieve_relevant_memories(
            store=store,
            user_id=uuid4(),
            query="q",
            scope=RetrievalScope(kinds=("case", "strategy")),
        )

    assert store.searched == ["case", "strategy"]


class _EmbeddingDownStore(AsyncBatchedBaseStore):
    """A batched store whose embedding step refuses a batch that carries a query."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str | None]] = []

    async def abatch(self, ops: Iterable[SearchOp]) -> list[Result]:
        batched = list(ops)
        self.batches.append([op.query for op in batched])
        queries = [op.query for op in batched if op.query is not None]
        if queries:
            raise EmbeddingUnavailableError(batch_size=len(queries), cause="test")
        when = datetime.now(UTC)
        return [[_stored_row(op.namespace_prefix, when)] for op in batched]


def _stored_row(namespace: tuple[str, ...], when: datetime) -> SearchItem:
    kind = namespace[-1]
    return SearchItem(
        namespace,
        f"{kind}-1",
        {
            "kind": kind,
            "name": kind,
            "summary": "y",
            "content": {},
            "created_at": when.isoformat(),
        },
        when,
        when,
    )


@pytest.mark.asyncio
async def test_an_unreachable_embedder_still_answers_the_listed_kinds() -> None:
    """The listed kinds answer from SQL and every ranked kind contributes nothing."""
    raw = _EmbeddingDownStore()

    found = await retrieve_relevant_memories(
        store=MemoryStore(store=raw, application_id="test"),
        user_id=uuid4(),
        query="find kinases",
        scope=RetrievalScope(
            kinds=("case", "strategy", "preference"),
            always_kinds=("preference",),
        ),
    )

    assert [hit.key for hit in found] == ["preference-1"]
    assert raw.batches == [[None], ["find kinases", "find kinases"]]
