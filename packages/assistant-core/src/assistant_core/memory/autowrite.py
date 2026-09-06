"""Writing a turn's memory candidates, honoring the user's deletions.

What counts as a candidate is the product's; this module only writes the ones
the user has not tombstoned.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from assistant_core.memory.schemas import MemoryValue
from assistant_core.memory.store import MemoryStore
from assistant_core.memory.tombstones import (
    TombstoneRepository,
    compute_content_hash,
)

MemoryCandidate = tuple[MemoryValue, str]


async def auto_write_memories(
    *,
    store: MemoryStore,
    tombstones: TombstoneRepository,
    user_id: UUID,
    candidates: Sequence[MemoryCandidate],
) -> int:
    """Write each candidate under its own key. Returns how many were written.

    Keys are the caller's, so a later turn updates a memory rather than
    duplicating it. All tombstone checks are batched into a single SELECT, so
    the number of DB round-trips is ``O(1)`` regardless of the candidate count.
    """
    if not candidates:
        return 0

    tombstoned = await tombstones.existing_hashes(
        user_id=user_id,
        values=[value for value, _key in candidates],
    )
    written = 0
    for value, key in candidates:
        content_hash = compute_content_hash(value.content)
        if (value.kind, content_hash) in tombstoned:
            continue
        await store.put(user_id=user_id, value=value, key=key)
        written += 1
    return written
