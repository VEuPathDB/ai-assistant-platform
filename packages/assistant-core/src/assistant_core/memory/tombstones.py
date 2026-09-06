from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.memory.schemas import MemoryValue, TombstoneReason
from assistant_core.persistence.models import MemoryTombstoneRow
from assistant_core.platform.context import calling_application

SessionFactory = Callable[[], AsyncSession]


def compute_content_hash(content: dict[str, object]) -> str:
    """Stable SHA-256 over a canonicalized dict representation.

    Fail-fast on non-JSON-serialisable values instead of ``default=str``:
    silently coercing unknown objects to their string form risks
    collisions (two instances that happen to ``str()`` identically hash
    the same) and hides accidental inputs. ``default=repr`` gives a
    richer but still-typed representation so callers notice when they
    feed the tombstone a value it doesn't natively understand.
    """
    serialized = json.dumps(content, sort_keys=True, default=repr)
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True)
class TombstoneRepository:
    """Soft-delete index for the memories of one user in one application.

    All reads and writes go through ``session_factory``. Use
    :meth:`existing_hashes` for batch lookups when you are about to check
    several candidate memories at once — it opens a single session.
    """

    session_factory: SessionFactory

    async def exists(self, *, user_id: UUID, value: MemoryValue) -> bool:
        hashes = await self.existing_hashes(
            user_id=user_id,
            values=[value],
        )
        return (value.kind, compute_content_hash(value.content)) in hashes

    async def existing_hashes(
        self,
        *,
        user_id: UUID,
        values: Sequence[MemoryValue],
    ) -> set[tuple[str, str]]:
        """Batch-check tombstones for a list of candidate values.

        Returns the set of ``(kind, content_hash)`` pairs that are
        tombstoned. Uses a single SELECT against a ``(kind, content_hash)``
        tuple IN clause — O(1) round-trips regardless of ``len(values)``.
        """
        if not values:
            return set()
        pairs: list[tuple[str, str]] = [
            (v.kind, compute_content_hash(v.content)) for v in values
        ]
        async with self.session_factory() as session:
            stmt = select(
                MemoryTombstoneRow.kind,
                MemoryTombstoneRow.content_hash,
            ).where(
                MemoryTombstoneRow.user_id == user_id,
                MemoryTombstoneRow.application_id == calling_application(),
                tuple_(
                    MemoryTombstoneRow.kind,
                    MemoryTombstoneRow.content_hash,
                ).in_(pairs),
            )
            rows = (await session.execute(stmt)).all()
        return {(row[0], row[1]) for row in rows}

    async def tombstone(
        self,
        *,
        user_id: UUID,
        value: MemoryValue,
        reason: TombstoneReason = "user_deleted",
    ) -> None:
        content_hash = compute_content_hash(value.content)
        async with self.session_factory() as session:
            stmt = (
                pg_insert(MemoryTombstoneRow)
                .values(
                    user_id=user_id,
                    application_id=calling_application(),
                    kind=value.kind,
                    content_hash=content_hash,
                    reason=reason,
                    deleted_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "user_id",
                        "application_id",
                        "kind",
                        "content_hash",
                    ],
                )
            )
            await session.execute(stmt)
            await session.commit()
