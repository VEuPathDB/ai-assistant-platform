"""What a durable tool declares, and the value that answers its parked call.

A durable tool hands its work to a worker and defers its call. The registry
here keeps what the tool declared, so the turn that delivers the worker's
result can build the chunks the tool would have emitted itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import DeferredToolResults
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk

from assistant_core.graph.turn_state import (
    DurableCall,
    DurableTaskResult,
    PendingDurableCall,
)

type ChunkBuilder = Callable[[Any, UUID, str | None], list[BaseChunk]]


@dataclass(frozen=True)
class DurableToolSpec:
    """One durable tool, as it declared itself."""

    tool_name: str
    estimated_duration_seconds: int
    chunks_from_result: ChunkBuilder | None = None


DURABLE_TOOLS: dict[str, DurableToolSpec] = {}


def register_durable_tool(spec: DurableToolSpec) -> None:
    """Record a durable tool's declaration under its registered name."""
    DURABLE_TOOLS[spec.tool_name] = spec


def _durable_tool_return(
    call: DurableCall,
    result: DurableTaskResult,
) -> ToolReturn[dict[str, JsonValue]]:
    """The value and the chunks one durable tool would have returned."""
    payload = result.as_tool_value()
    spec = DURABLE_TOOLS.get(call.durable_tool_name)
    chunks: list[BaseChunk] = []
    if spec is not None and spec.chunks_from_result is not None:
        chunks = spec.chunks_from_result(payload, call.task_id, call.tool_call_id)
    return ToolReturn(return_value=payload, metadata=chunks)


def durable_tool_results(
    parked: PendingDurableCall,
    answers: Mapping[UUID, DurableTaskResult],
) -> DeferredToolResults:
    """Every parked durable call, answered by its own task's result."""
    return DeferredToolResults(
        calls={
            call.tool_call_id: _durable_tool_return(call, answers[call.task_id])
            for call in parked.durable_calls
        },
    )


__all__ = [
    "DURABLE_TOOLS",
    "ChunkBuilder",
    "DurableToolSpec",
    "durable_tool_results",
    "register_durable_tool",
]
