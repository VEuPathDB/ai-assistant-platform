from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from assistant_core.platform.pydantic_base import CamelModel

# The shape of a kind, which the runtime owns. Which kinds exist is the host's:
# it declares them on ``AssistantSpec.memory_kinds`` and publishes them itself.
_KIND_SHAPE = re.compile(r"[a-z][a-z0-9_]*")

TombstoneReason = Literal["user_deleted", "auto_pruned"]


class MemoryValue(CamelModel):
    kind: str
    name: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    site_id: str | None = None
    content: dict[str, object]
    auto_retrieve: bool = True
    source_conversation_id: UUID | None = None
    created_at: datetime
    last_used_at: datetime | None = None

    @field_validator("kind")
    @classmethod
    def _kind_is_a_name(cls, value: str) -> str:
        if _KIND_SHAPE.fullmatch(value) is None:
            msg = "a memory kind is a non-empty snake_case name"
            raise ValueError(msg)
        return value


class MemoryEntryDraft(CamelModel):
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Short, recall-friendly title.",
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
            "Structured payload: the durable knowledge itself, so future runs "
            "can act on it."
        ),
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Optional retrieval tags.",
    )
