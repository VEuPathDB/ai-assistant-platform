"""The cache half of the write-through store, with the database stubbed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from assistant_core.platform.store import WriteThruStore


@dataclass(frozen=True)
class _Note:
    id: str
    text: str


class _NoteStore(WriteThruStore[_Note]):
    """A store whose database is a dict, so the cache rules are visible."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, _Note] = {}

    async def _persist(self, entity: _Note) -> None:
        self.rows[entity.id] = entity

    async def _load(self, entity_id: str) -> _Note | None:
        return self.rows.get(entity_id)

    async def _delete_from_db(self, entity_id: str) -> None:
        self.rows.pop(entity_id, None)


async def test_a_saved_entity_is_readable_before_its_row_is_written() -> None:
    store = _NoteStore()

    store.save(_Note(id="n1", text="first"))

    assert store.get("n1") == _Note(id="n1", text="first")
    assert store.rows == {}

    await asyncio.sleep(0)

    assert store.rows == {"n1": _Note(id="n1", text="first")}


async def test_an_entity_outside_the_cache_is_loaded_and_cached() -> None:
    store = _NoteStore()
    store.rows["n2"] = _Note(id="n2", text="second")

    assert store.get("n2") is None
    assert await store.aget("n2") == _Note(id="n2", text="second")
    assert store.get("n2") == _Note(id="n2", text="second")


async def test_deleting_what_the_cache_does_not_hold_reports_nothing_removed() -> None:
    store = _NoteStore()

    assert store.delete("missing") is False
    assert await store.adelete("missing") is False


async def test_a_sync_delete_drops_the_cached_entity_and_the_row() -> None:
    store = _NoteStore()
    store.save(_Note(id="n4", text="fourth"))
    await asyncio.sleep(0)

    assert store.delete("n4") is True

    await asyncio.sleep(0)

    assert store.get("n4") is None
    assert store.rows == {}


async def test_an_async_delete_removes_the_row_and_the_cached_entity() -> None:
    store = _NoteStore()
    store.save(_Note(id="n3", text="third"))
    await asyncio.sleep(0)

    assert await store.adelete("n3") is True
    assert store.get("n3") is None
    assert await store.aget("n3") is None
