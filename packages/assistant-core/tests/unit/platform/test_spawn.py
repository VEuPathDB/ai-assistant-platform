"""Fire-and-forget tasks keep a strong reference until they finish."""

from __future__ import annotations

import asyncio

import assistant_core.platform.spawn
from assistant_core.platform.spawn import spawn


async def test_a_spawned_task_is_retained_until_it_finishes() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _work() -> None:
        started.set()
        await release.wait()

    task = spawn(_work(), name="work")
    await started.wait()

    assert task is not None
    assert task in assistant_core.platform.spawn._background_tasks

    release.set()
    await task

    assert task not in assistant_core.platform.spawn._background_tasks


def test_a_coroutine_spawned_outside_a_loop_is_closed() -> None:
    ran = False

    async def _work() -> None:
        nonlocal ran
        ran = True

    assert spawn(_work()) is None
    assert ran is False
