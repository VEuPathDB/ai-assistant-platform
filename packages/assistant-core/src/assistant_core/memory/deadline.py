"""The bound every turn puts on a memory-store call."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from assistant_core.platform.config import get_runtime_settings


class MemoryStoreTimeoutError(TimeoutError):
    """The memory store did not answer inside the turn's window."""

    def __init__(self, *, operation: str, seconds: float) -> None:
        self.operation = operation
        self.seconds = seconds
        message = (
            f"The memory store did not answer {operation} within {seconds} seconds."
        )
        super().__init__(message)


@asynccontextmanager
async def memory_store_deadline(operation: str) -> AsyncIterator[None]:
    """Bound a store call, so a turn cannot wait on it without end."""
    seconds = get_runtime_settings().memory_store_timeout_seconds
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            yield
    except TimeoutError as exc:
        if deadline.expired():
            raise MemoryStoreTimeoutError(
                operation=operation,
                seconds=seconds,
            ) from exc
        raise
