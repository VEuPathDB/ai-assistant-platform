"""An in-memory cache of entities, backed by fire-and-forget row writes.

A subclass supplies its ORM model and the two row converters; the base derives
the upsert, the load and the delete from them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import get_logger
from assistant_core.platform.spawn import spawn

logger = get_logger(__name__)


class Identifiable(Protocol):
    """Any entity with a string ``id``."""

    @property
    def id(self) -> str: ...


class WriteThruStore[T: Identifiable]:
    """A cache of entities whose rows are written outside the caller's turn.

    A subclass sets ``_model`` to its ORM model, ``_to_row`` to the column
    values of one entity, and ``_from_row`` to the entity a row rebuilds.
    """

    _model: Any = None
    _to_row: Callable[[T], dict[str, object]] = cast(
        "Callable[[T], dict[str, object]]",
        cast("object", None),
    )
    _from_row: Callable[..., T] = cast("Callable[..., T]", cast("object", None))

    def __init__(self) -> None:
        self._cache: dict[str, T] = {}

    async def _persist(self, entity: T) -> None:
        """Write the entity's row. A failed write leaves the cache alone."""
        try:
            await self._persist_with_retry(entity)
        except Exception:
            logger.exception(
                "Failed to persist entity to DB",
                entity_type=self._model.__tablename__,
                entity_id=entity.id,
            )

    @retry(
        retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, max=2),
        reraise=True,
    )
    async def _persist_with_retry(self, entity: T) -> None:
        vals = self._to_row(entity)
        stmt = (
            pg_insert(self._model)
            .values(**vals)
            .on_conflict_do_update(
                index_elements=[self._model.id],
                set_={k: v for k, v in vals.items() if k != "id"},
            )
        )
        async with async_session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def _load(self, entity_id: str) -> T | None:
        """The entity this row holds, or None when there is no such row."""
        async with async_session_factory() as session:
            row = await session.get(self._model, entity_id)
            if row is None:
                return None
            return self._from_row(row)

    async def _delete_from_db(self, entity_id: str) -> None:
        """Delete the entity's row. A failed delete leaves the cache alone."""
        try:
            await self._delete_from_db_with_retry(entity_id)
        except Exception:
            logger.exception(
                "Failed to delete entity from DB",
                entity_type=self._model.__tablename__,
                entity_id=entity_id,
            )

    @retry(
        retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, max=2),
        reraise=True,
    )
    async def _delete_from_db_with_retry(self, entity_id: str) -> None:
        stmt = sa_delete(self._model).where(self._model.id == entity_id)
        async with async_session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    def save(self, entity: T) -> None:
        self._cache[entity.id] = entity
        spawn(self._persist(entity), name=f"persist-{entity.id}")

    def get(self, entity_id: str) -> T | None:
        return self._cache.get(entity_id)

    def delete(self, entity_id: str) -> bool:
        removed = self._cache.pop(entity_id, None) is not None
        if removed:
            spawn(self._delete_from_db(entity_id), name=f"delete-{entity_id}")
        return removed

    async def aget(self, entity_id: str) -> T | None:
        entity = self._cache.get(entity_id)
        if entity is not None:
            return entity
        entity = await self._load(entity_id)
        if entity is not None:
            self._cache[entity_id] = entity
        return entity

    async def adelete(self, entity_id: str) -> bool:
        removed = entity_id in self._cache
        self._cache.pop(entity_id, None)
        await self._delete_from_db(entity_id)
        return removed


__all__ = ["Identifiable", "WriteThruStore"]
