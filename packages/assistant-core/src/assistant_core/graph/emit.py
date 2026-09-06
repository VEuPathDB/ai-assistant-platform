"""Writing one AI SDK chunk to the turn's stream."""

from __future__ import annotations

from typing import Any

from pydantic_ai.ui.vercel_ai.response_types import BaseChunk

from assistant_core.graph.stream_events import turn_usage_event


def emit_chunk(writer: Any, chunk: BaseChunk) -> None:
    writer(
        {
            "chunk": chunk.model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
        },
    )


def emit_turn_usage(writer: Any, total_tokens: int, cost_usd: str) -> None:
    emit_chunk(writer, turn_usage_event(total_tokens=total_tokens, cost_usd=cost_usd))


__all__ = ["emit_chunk", "emit_turn_usage"]
