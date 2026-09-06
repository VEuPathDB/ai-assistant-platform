"""Memories and their tombstones belong to one application."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from tests.conftest import seed_host_user

from assistant_core.memory.lifespan import lifespan_memory_store
from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore
from assistant_core.memory.tombstones import TombstoneRepository
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory

HOME = "pathfinder"
OTHER = "companion"


@pytest.fixture
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


def _value(name: str = "kinome") -> MemoryValue:
    return MemoryValue(
        kind="knowledge",
        name=name,
        summary="the kinome has 105 members",
        content={"count": 105},
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_a_memory_of_one_application_is_unreachable_from_another(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    async with lifespan_memory_store(os.environ["DATABASE_URL"]) as raw:
        store = MemoryStore(store=raw)
        key = await store.put(user_id=user_id, value=_value())

        token = application_id_ctx.set(OTHER)
        try:
            elsewhere = await store.get(user_id=user_id, kind="knowledge", key=key)
            listed = await store.list_all(user_id=user_id, kind="knowledge")
            hits = await store.semantic_search(
                user_id=user_id,
                kind="knowledge",
                query="kinome size",
            )
        finally:
            application_id_ctx.reset(token)

        assert elsewhere is None
        assert listed == []
        assert hits == []
        assert await store.get(user_id=user_id, kind="knowledge", key=key) is not None


@pytest.mark.asyncio
async def test_deleting_under_one_application_leaves_the_other_untouched(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    async with lifespan_memory_store(os.environ["DATABASE_URL"]) as raw:
        store = MemoryStore(store=raw)
        key = await store.put(user_id=user_id, value=_value(), key="shared-key")
        token = application_id_ctx.set(OTHER)
        try:
            await store.put(user_id=user_id, value=_value("other"), key=key)
            await store.delete(user_id=user_id, kind="knowledge", key=key)
        finally:
            application_id_ctx.reset(token)

        mine = await store.get(user_id=user_id, kind="knowledge", key=key)

    assert mine is not None
    assert mine.value.name == "kinome"


@pytest.mark.asyncio
async def test_a_tombstone_of_one_application_does_not_block_another(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)
    tombstones = TombstoneRepository(session_factory=async_session_factory)
    value = _value()

    await tombstones.tombstone(user_id=user_id, value=value)

    assert await tombstones.exists(user_id=user_id, value=value) is True
    token = application_id_ctx.set(OTHER)
    try:
        assert await tombstones.exists(user_id=user_id, value=value) is False
    finally:
        application_id_ctx.reset(token)
