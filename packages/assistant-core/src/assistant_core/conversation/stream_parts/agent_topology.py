"""The parts of an assistant whose agents are a lead and its sub-agents.

The runtime emits none of them. An assistant with this topology registers them
on its own registry and calls the builders from its graph.
"""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue
from pydantic_ai.ui.vercel_ai.response_types import DataChunk

from assistant_core.conversation.stream_parts.registry import StreamPartRegistry
from assistant_core.platform.pydantic_base import CamelModel


class LeadUsagePayload(CamelModel):
    """Payload for the lead-usage chunk. The counts cover the lead agent only
    and exclude sub-agents. ``context_tokens`` is the input size of the latest
    request against ``context_window``, and 0 in either means unknown.
    """

    model_id: str = ""
    tokens: int = 0
    cost_usd: str = "0"
    context_tokens: int = 0
    context_window: int = 0


def lead_usage_event(
    *,
    model_id: str,
    tokens: int,
    cost_usd: str,
    context_tokens: int = 0,
    context_window: int = 0,
) -> DataChunk:
    """Report live lead usage. The id is stable, so repeated emissions
    reconcile into one persisted part."""
    return DataChunk(
        type="data-lead-usage",
        id="lead-usage",
        data=LeadUsagePayload(
            model_id=model_id,
            tokens=tokens,
            cost_usd=cost_usd,
            context_tokens=context_tokens,
            context_window=context_window,
        ).model_dump(by_alias=True, mode="json"),
    )


class SubAgentCallPayload(CamelModel):
    """Payload for the sub-agent-call chunk. The tool call id identifies the
    dispatch, and sub-agent step chunks join to it. ``context_tokens`` is the
    input size of the dispatch's latest request against ``context_window``, and
    0 in either means unknown.
    """

    tool_call_id: str
    sub_agent: str
    phase: str
    state: Literal["started", "completed", "failed"]
    model_id: str = ""
    summary: str = ""
    succeeded: bool | None = None
    tokens: int = 0
    cost_usd: str = "0"
    context_tokens: int = 0
    context_window: int = 0


def sub_agent_call_event(payload: SubAgentCallPayload) -> DataChunk:
    """Report one sub-agent dispatch. The id is the tool call id, so the
    started and completed emissions reconcile into one part."""
    return DataChunk(
        type="data-sub-agent-call",
        id=payload.tool_call_id,
        data=payload.model_dump(by_alias=True, mode="json"),
    )


class SubAgentStepPayload(CamelModel):
    """Payload for one event inside a sub-agent run. The parent tool call id
    nests the event under its dispatch.
    """

    parent_tool_call_id: str
    kind: Literal["tool", "reasoning", "text"]
    state: Literal["started", "completed", "failed", "denied"]
    tool_call_id: str | None = None
    tool_name: str | None = None
    args: dict[str, JsonValue] | None = None
    result_summary: str | None = None
    text: str | None = None


def sub_agent_step_event(payload: SubAgentStepPayload) -> DataChunk:
    """One event inside a sub-agent's run."""
    return DataChunk(
        type="data-sub-agent-step",
        data=payload.model_dump(by_alias=True, mode="json"),
    )


def register_agent_topology_stream_parts(registry: StreamPartRegistry) -> None:
    """Register the three kinds on the registry of the assistant that emits them."""
    registry.register("data-lead-usage", LeadUsagePayload)
    registry.register("data-sub-agent-call", SubAgentCallPayload)
    registry.register("data-sub-agent-step", SubAgentStepPayload)


__all__ = [
    "LeadUsagePayload",
    "SubAgentCallPayload",
    "SubAgentStepPayload",
    "lead_usage_event",
    "register_agent_topology_stream_parts",
    "sub_agent_call_event",
    "sub_agent_step_event",
]
