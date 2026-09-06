"""The one line a tool writes about its own call, carried on its return metadata."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import RunContext
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk

from assistant_core.graph.stream_events import (
    TOOL_SUMMARY_LIMIT,
    ToolSummaryStatus,
    tool_summary_event,
)


def truncate_summary(text: str, *, limit: int = TOOL_SUMMARY_LIMIT) -> str:
    """One summary line from text a user or a site wrote.

    The line is plain ASCII on one line, at most ``limit`` characters, cut on
    a word boundary, and it carries no trailing period. A summary chunk
    refuses anything else, so every echo of outside text passes through here.
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    flat = " ".join(folded.split())
    if len(flat) > limit:
        cut = flat[:limit].rstrip()
        boundary = cut.rfind(" ")
        if boundary > 0:
            cut = cut[:boundary]
        flat = cut
    return flat.rstrip(". ")


def count_noun(count: int, noun: str) -> str:
    """A count with its noun in the number the count needs."""
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def summary_chunks(
    tool_call_id: str | None,
    summary: str,
    *,
    status: ToolSummaryStatus = "ok",
) -> list[BaseChunk]:
    """The summary chunk for one call, or nothing when there is none to send.

    The line is normalized here, so a study title in Greek or a description
    over the limit never turns a tool call into a validation error. A summary
    that names no call is unreducible, and one that normalizes to nothing says
    nothing; both are dropped.
    """
    line = truncate_summary(summary)
    if tool_call_id is None or not line:
        return []
    return [
        tool_summary_event(
            tool_call_id=tool_call_id,
            summary=line,
            status=status,
        ),
    ]


def with_summary[T](
    value: T,
    summary: str,
    *,
    ctx: RunContext[Any],
    status: ToolSummaryStatus = "ok",
    extra: Sequence[BaseChunk] = (),
) -> ToolReturn[T]:
    """Return a tool's value with its one-line summary and any other chunks."""
    chunks: list[BaseChunk] = [
        *extra,
        *summary_chunks(ctx.tool_call_id, summary, status=status),
    ]
    return ToolReturn(return_value=value, metadata=chunks)
