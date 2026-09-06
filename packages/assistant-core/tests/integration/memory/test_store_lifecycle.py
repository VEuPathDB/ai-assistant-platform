"""The store's background batch task lives exactly as long as the store."""

from __future__ import annotations

import asyncio
import os

import pytest

from assistant_core.memory.lifespan import lifespan_memory_store


@pytest.mark.asyncio
async def test_the_batch_task_ends_with_the_store(
    db_cleaner: None,
    patch_app_db_engine: None,
) -> None:
    """A closed store leaves no pending task behind."""
    del db_cleaner, patch_app_db_engine
    database_url = os.environ["DATABASE_URL"]
    before = asyncio.all_tasks()

    async with lifespan_memory_store(database_url) as store:
        assert await store.aget(("probe", "none"), "absent") is None
        opened = [task for task in asyncio.all_tasks() if task not in before]
        assert len(opened) == 1
        assert not opened[0].done()

    assert opened[0].done()
