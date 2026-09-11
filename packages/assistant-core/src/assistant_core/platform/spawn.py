"""Fire-and-forget asyncio tasks that survive the garbage collector.

``asyncio.create_task`` returns a task the collector may cancel while it runs
unless something holds a strong reference to it. Every task spawned here is
held until it finishes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_background_tasks: set[asyncio.Task[Any]] = set()


def spawn(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any] | None:
    """Schedule the coroutine and keep it alive until it finishes.

    A caller outside a running loop schedules nothing: the coroutine is closed
    and the answer is ``None``.
    """
    try:
        task = asyncio.create_task(coro, name=name)
    except RuntimeError:
        coro.close()
        return None
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


__all__ = ["spawn"]
