from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from langgraph.store.base import Item, SearchItem
from langgraph.store.postgres.aio import AsyncPostgresStore

from assistant_core.embeddings.embedder import EmbeddingUnavailableError
from assistant_core.memory.embedding import format_embedded_string
from assistant_core.memory.schemas import MemoryValue
from assistant_core.platform.context import calling_application
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

MemoryNamespace = tuple[str, str, str, str, str]


def memory_namespace(
    *,
    user_id: UUID,
    kind: str,
    application_id: str | None = None,
) -> MemoryNamespace:
    """Namespace one memory under an application, a user and a kind.

    The application defaults to the one the request or the job runs as, so a
    memory never leaves the application that wrote it.
    """
    resolved = application_id if application_id is not None else calling_application()
    return ("app", resolved, "user", str(user_id), kind)


@dataclass(frozen=True)
class StoredMemory:
    """Memory as seen by callers — carries the storage key + optional score.

    ``score`` is only populated by :meth:`MemoryStore.semantic_search` (pulled
    from the HNSW index via ``Item.score``). Both ``list_all`` and ``get``
    leave it as ``None``.
    """

    key: str
    value: MemoryValue
    score: float | None = None


@dataclass(frozen=True)
class MemoryStore:
    """High-level API over LangGraph AsyncPostgresStore.

    Keys are auto-generated UUIDs unless caller supplies one. Namespaces come
    from :func:`memory_namespace`. The stored payload is the raw
    :class:`MemoryValue` serialisation — the backing
    :class:`AsyncPostgresStore` embeds the fields configured in
    ``lifespan_memory_store`` (kind, name, tags, summary).

    ``application_id`` names the application to read and write as. Left unset,
    every call follows the application on the context.
    """

    store: AsyncPostgresStore
    application_id: str | None = None

    def _ns(self, user_id: UUID, kind: str) -> MemoryNamespace:
        return memory_namespace(
            user_id=user_id,
            kind=kind,
            application_id=self.application_id,
        )

    async def put(
        self,
        *,
        user_id: UUID,
        value: MemoryValue,
        key: str | None = None,
    ) -> str:
        mem_key = key or str(uuid4())
        payload = _dump_for_store(value)
        await self.store.aput(self._ns(user_id, value.kind), mem_key, payload)
        return mem_key

    async def get(
        self,
        *,
        user_id: UUID,
        kind: str,
        key: str,
    ) -> StoredMemory | None:
        item = await self.store.aget(self._ns(user_id, kind), key)
        return _to_stored_get(item)

    async def delete(
        self,
        *,
        user_id: UUID,
        kind: str,
        key: str,
    ) -> None:
        await self.store.adelete(self._ns(user_id, kind), key)

    async def list_all(
        self,
        *,
        user_id: UUID,
        kind: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredMemory]:
        items = await self.store.asearch(
            self._ns(user_id, kind),
            query=None,
            limit=limit,
            offset=offset,
        )
        return [_to_stored_search(i) for i in items]

    async def semantic_search(
        self,
        *,
        user_id: UUID,
        kind: str,
        query: str,
        top_k: int = 8,
    ) -> list[StoredMemory]:
        """The nearest memories, or none when the embedding API is unreachable."""
        try:
            items = await self.store.asearch(
                self._ns(user_id, kind),
                query=query,
                limit=top_k,
            )
        except EmbeddingUnavailableError as exc:
            logger.warning("Memory search returned nothing", error=str(exc))
            return []
        return [_to_stored_search(i) for i in items]


def _dump_for_store(value: MemoryValue) -> dict[str, object]:
    """Serialise MemoryValue with a single synthetic field for embedding.

    LangGraph's store embeds one vector per configured ``fields`` key per
    item. Listing the raw kind/name/tags/summary as separate fields would
    cost 4x per put — instead we write the concatenated string to
    ``_embed_text`` and point the index config at that single key. The
    synthetic key is popped on read so it never leaks into
    :class:`MemoryValue`.
    """
    payload = value.model_dump(mode="json")
    payload["_embed_text"] = format_embedded_string(value)
    return payload


def _to_stored_get(item: Item | None) -> StoredMemory | None:
    """Convert a plain ``Item`` (from ``aget``) — no score populated."""
    if item is None:
        return None
    return StoredMemory(
        key=item.key,
        value=_parse_memory(item.value),
        score=None,
    )


def _to_stored_search(item: SearchItem) -> StoredMemory:
    """Convert a ``SearchItem`` (from ``asearch``) — carries the HNSW score."""
    return StoredMemory(
        key=item.key,
        value=_parse_memory(item.value),
        score=item.score,
    )


def _parse_memory(raw_value: dict[str, object]) -> MemoryValue:
    payload = dict(raw_value)
    payload.pop("_embed_text", None)
    return MemoryValue.model_validate(payload)
