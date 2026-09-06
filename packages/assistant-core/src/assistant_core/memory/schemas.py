from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from assistant_core.platform.pydantic_base import CamelModel

# The kinds this deployment publishes on ``/api/v1/memories``. The store, the
# retriever and the tombstone index all take a kind as a plain string; only the
# wire payload narrows it.
MemoryKind = Literal["gene_set", "strategy", "preference", "knowledge", "case"]

TombstoneReason = Literal["user_deleted", "auto_pruned"]


class MemoryValue(CamelModel):
    kind: MemoryKind
    name: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    site_id: str | None = None
    content: dict[str, object]
    auto_retrieve: bool = True
    source_conversation_id: UUID | None = None
    created_at: datetime
    last_used_at: datetime | None = None


class MemoryEntryDraft(CamelModel):
    name: str = Field(
        min_length=1,
        max_length=200,
        description=(
            'Short, recall-friendly title (e.g. "P. falciparum kinome size").'
        ),
    )
    summary: str = Field(
        min_length=1,
        max_length=400,
        description=(
            "One-line summary shown in retrieval previews. The retriever "
            "matches against this + the content payload."
        ),
    )
    content: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Structured payload — the durable knowledge itself (counts, "
            "identifiers, criteria, etc.) so future runs can act on it."
        ),
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Optional retrieval tags (organism, technique, dataset). "
            "Site id is added automatically — don't repeat it here."
        ),
    )
