"""A named database lock one process holds for as long as it lives."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text

from assistant_core.platform.db import get_engine

_TAKE = text("SELECT pg_try_advisory_lock(hashtextextended(:name, 0))")
_RELEASE = text("SELECT pg_advisory_unlock(hashtextextended(:name, 0))")


@asynccontextmanager
async def advisory_lease(name: str) -> AsyncIterator[bool]:
    """Take a session-level lock of this name, and report whether it was free.

    The lock lives on the connection this holds open, so a process that stops
    releases it and the next caller of the same name takes it. The transaction
    is closed at once, because the hold is the connection and not the
    transaction.
    """
    async with get_engine().connect() as connection:
        taken = bool(await connection.scalar(_TAKE, {"name": name}))
        await connection.commit()
        try:
            yield taken
        finally:
            if taken:
                await connection.execute(_RELEASE, {"name": name})
                await connection.commit()


__all__ = ["advisory_lease"]
