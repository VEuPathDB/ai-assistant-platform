"""Compaction: when a scratchpad grows past its ceilings, a model rewrites it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field
from pydantic_ai import Agent

from assistant_core.cost import cost_for_run
from assistant_core.platform.db import DBSessionFactory
from assistant_core.platform.logging import get_logger
from assistant_core.platform.pydantic_base import CamelModel
from assistant_core.scratchpad.ids import approx_body_tokens
from assistant_core.scratchpad.models import CompactionRun, Note, NoteCreate
from assistant_core.scratchpad.notebook import CompactionFacts, ScratchpadNotebook

logger = get_logger(__name__)

COMPACT_COUNT_THRESHOLD = 50
COMPACT_TOKENS_THRESHOLD = 10000

MAX_COMPACTED_NOTES = 20


class CompactionResult(CamelModel):
    """The notes that replace the unpinned set."""

    notes: list[NoteCreate] = Field(max_length=MAX_COMPACTED_NOTES)


@dataclass
class CompactorDeps:
    """The notes the compactor is asked to rewrite, already rendered."""

    input_notes_markdown: str


type CompactorAgent = Agent[CompactorDeps, CompactionResult]


def _format_notes_for_compactor(notes: list[Note]) -> str:
    lines: list[str] = []
    for n in notes:
        lines.append(f"### [{n.id}] {n.title}")
        lines.append(f"summary: {n.summary}")
        if n.tags:
            lines.append(f"tags: {', '.join(n.tags)}")
        lines.append("")
        lines.append(n.body)
        lines.append("")
    return "\n".join(lines)


def _enforce_budget(
    new_notes: list[NoteCreate],
    *,
    threshold_tokens: int,
) -> list[NoteCreate]:
    """Drop the oldest replacements until the set fits the token ceiling."""
    trimmed = list(new_notes)
    while (
        trimmed and sum(approx_body_tokens(n.body) for n in trimmed) > threshold_tokens
    ):
        trimmed.pop(0)
    return trimmed


def _trigger_reason(
    *,
    over_count: bool,
    over_tokens: bool,
) -> Literal["count", "tokens", "both"]:
    if over_count and over_tokens:
        return "both"
    return "count" if over_count else "tokens"


async def compact_scratchpad(
    *,
    conversation_id: UUID,
    db_session_factory: DBSessionFactory,
    agent: Callable[[], CompactorAgent],
    count_threshold: int = COMPACT_COUNT_THRESHOLD,
    tokens_threshold: int = COMPACT_TOKENS_THRESHOLD,
) -> CompactionRun | None:
    """Rewrite the unpinned notes when they pass a ceiling, else return None.

    The gate counts only the unpinned notes, because compaction cannot touch
    a pinned one and a gate that counted them would run forever. ``agent``
    builds the compactor, and runs only when a ceiling is passed. A failure of
    the model run reaches the caller, which decides whether the turn survives.
    """
    notebook = ScratchpadNotebook(db_session_factory, conversation_id)
    totals = await notebook.compaction_totals()

    over_count = totals.compactable_count > count_threshold
    over_tokens = totals.compactable_tokens > tokens_threshold
    if not over_count and not over_tokens:
        return None
    reason = _trigger_reason(over_count=over_count, over_tokens=over_tokens)

    deps = CompactorDeps(
        input_notes_markdown=_format_notes_for_compactor(
            await notebook.notes_to_compact(),
        ),
    )
    result = await agent().run("Compact the notebook.", deps=deps)
    response = result.response
    cost = cost_for_run(
        usage=result.usage,
        model_name=response.model_name,
        provider_name=response.provider_name,
        provider_url=response.provider_url,
    )

    run = await notebook.commit_compaction(
        _enforce_budget(result.output.notes, threshold_tokens=tokens_threshold),
        CompactionFacts(
            triggered_at=datetime.now(UTC),
            before_count=totals.total_count,
            before_tokens=totals.total_tokens,
            model_id=response.model_name or "",
            cost_usd=cost,
            trigger_reason=reason,
        ),
    )

    logger.info(
        "scratchpad compaction completed",
        conversation_id=str(conversation_id),
        before_count=run.before_count,
        after_count=run.after_count,
        before_tokens=run.before_tokens,
        after_tokens=run.after_tokens,
        trigger_reason=reason,
        model_id=run.model_id,
        cost_usd=str(cost),
    )
    return run
