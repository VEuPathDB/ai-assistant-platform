"""One note of a thread's scratchpad, and the record of one compaction run."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from assistant_core.platform.pydantic_base import CamelModel


def _normalize_tags(raw: list[str]) -> list[str]:
    """Lowercase, strip, drop empty, deduplicate in insertion order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        cleaned = item.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


class Note(CamelModel):
    id: str
    conversation_id: UUID
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=16)
    pinned: bool = False
    body_tokens: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("tags")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return _normalize_tags(v)


class NoteCreate(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=16)
    pinned: bool = False

    @field_validator("tags")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return _normalize_tags(v)


class NoteUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=16)

    @field_validator("tags")
    @classmethod
    def _normalize(cls, v: list[str] | None) -> list[str] | None:
        return _normalize_tags(v) if v is not None else None


class NoteRef(CamelModel):
    """The shape an agent and a client read when the body is not needed."""

    id: str
    title: str
    summary: str
    tags: list[str]
    pinned: bool
    created_at: datetime


class NoteDetail(NoteRef):
    """The shape that adds the body and the time of the last write."""

    body: str
    body_tokens: int
    updated_at: datetime


class NoteListResult(CamelModel):
    """What a listing returns.

    ``total_notes`` is the size of the whole scratchpad, so an empty
    ``matches`` separates a missed filter from an empty scratchpad.
    """

    total_notes: int = Field(ge=0)
    matches: list[NoteRef]
    summary: str


class NoteSearchResult(NoteListResult):
    """A listing that answers one query."""

    query: str


class CompactionRun(CamelModel):
    id: int | None = None
    conversation_id: UUID
    triggered_at: datetime
    before_count: int
    after_count: int
    before_tokens: int
    after_tokens: int
    model_id: str
    cost_usd: Decimal
    trigger_reason: Literal["count", "tokens", "both"]
