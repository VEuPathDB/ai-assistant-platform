"""The bound every turn puts on a checkpoint call."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from assistant_core.platform.config import get_runtime_settings


class CheckpointTimeoutError(TimeoutError):
    """The checkpointer did not answer inside the turn's window."""

    def __init__(self, *, operation: str, seconds: float) -> None:
        self.operation = operation
        self.seconds = seconds
        message = (
            f"The checkpointer did not answer {operation} within {seconds} seconds."
        )
        super().__init__(message)


@asynccontextmanager
async def checkpoint_deadline(operation: str) -> AsyncIterator[None]:
    """Bound a checkpoint round trip, so a turn cannot wait on it without end."""
    seconds = get_runtime_settings().checkpoint_timeout_seconds
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            yield
    except TimeoutError as exc:
        if deadline.expired():
            raise CheckpointTimeoutError(
                operation=operation,
                seconds=seconds,
            ) from exc
        raise
