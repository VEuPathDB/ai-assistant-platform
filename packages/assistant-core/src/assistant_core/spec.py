"""What an assistant declares to the runtime.

The runtime owns turns, durability, streaming, memory, guards, cost and
identity enforcement; the assistant owns its graph, state, parts, kinds, test
double and identity requirement. Nothing here names a product.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.ui.vercel_ai.request_types import TextUIPart, ToolApprovalResponded

from assistant_core.conversation.stream_parts.registry import (
    StreamPartRegistry,
)
from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_state import (
    DurableTaskResult,
    TurnState,
    UserQuestionAnswer,
)
from assistant_core.mcp.declaration import ToolSourceDeclarations
from assistant_core.persistence.models import Conversation
from assistant_core.platform.types import ReasoningEffort


class TurnStart(BaseModel):
    """The turn's inputs, before the assistant shapes them into its state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    user_id: UUID
    site_id: str
    mode: str
    turn_message_id: UUID
    turn_start_event_id: int
    turn_trace_id: str | None = None
    turn_created_at: str | None = None
    # An approval or consult answer re-enters a turn the checkpoint already
    # holds, so the message fields below stay out of the state update.
    is_resume: bool = False
    user_message_id: UUID | None = None
    user_prompt: str = ""
    # Set on the turn a worker opens to answer a durable call the thread parked.
    durable_result: DurableTaskResult | None = None
    # Every parked task's answer, when the step parked several calls.
    durable_results: tuple[DurableTaskResult, ...] = ()
    approval_responses: dict[str, ToolApprovalResponded] = Field(default_factory=dict)
    user_question_answers: dict[str, list[UserQuestionAnswer]] = Field(
        default_factory=dict,
    )

    def state_kwargs(self) -> dict[str, Any]:
        """The ``TurnState`` fields this turn sets."""
        base: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "site_id": self.site_id,
            "mode": self.mode,
            "turn_trace_id": self.turn_trace_id,
            "turn_created_at": self.turn_created_at,
            "turn_message_id": self.turn_message_id,
            "turn_start_event_id": self.turn_start_event_id,
            "turn_total_tokens": 0,
            "turn_total_cost_usd": Decimal(0),
            "approval_responses": dict(self.approval_responses),
            "user_question_answers": dict(self.user_question_answers),
            "retrieved_memories": [],
            # Always written, so a later turn never reads the answers again.
            "durable_result": self.durable_result,
            "durable_results": list(self.durable_results),
        }
        if self.is_resume:
            return base
        return {
            **base,
            "user_message_id": self.user_message_id,
            "user_prompt": self.user_prompt,
            "user_parts": [TextUIPart(text=self.user_prompt, state="done")],
        }


def turn_input(state: TurnState) -> dict[str, Any]:
    """The graph update for one turn: only the fields the assistant set.

    A field the assistant left alone keeps the value its checkpoint holds.
    """
    return {name: getattr(state, name) for name in state.model_fields_set}


@dataclass(frozen=True, kw_only=True)
class TurnContextRequest:
    """What the runtime knows before the assistant builds its turn context."""

    conversation: Conversation | None
    site_id: str
    user_id: UUID
    memory_store: AsyncPostgresStore | None
    cancel_event: asyncio.Event
    phase_models: dict[str, str]
    phase_reasoning: dict[str, ReasoningEffort]
    # The declared tool sources this turn resolved, keyed by their local name.
    # They hold their own credential; the assistant never reads one.
    tool_sources: Mapping[str, AbstractToolset[Any]] = field(default_factory=dict)


type GraphFactory = Callable[
    [BaseCheckpointSaver[Any]],
    CompiledStateGraph[Any, Any, Any, Any],
]
type TurnStateFactory = Callable[[TurnStart], TurnState]
type TurnContextFactory = Callable[[TurnContextRequest], Awaitable[TurnContext]]
type StreamPartHook = Callable[[StreamPartRegistry], None]
type MockModelFactory = Callable[[], Model]
type IdentityGate = Callable[[], Awaitable[None]]
type TurnEpilogue = Callable[[UUID], Awaitable[Sequence[dict[str, Any]]]]


class AssistantSpec(BaseModel):
    """One assistant, as the runtime sees it."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    assistant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    build_graph: GraphFactory
    build_initial_state: TurnStateFactory
    build_turn_context: TurnContextFactory
    build_mock_model: MockModelFactory
    checkpoint_types: tuple[type, ...] = ()
    register_stream_parts: StreamPartHook | None = None
    memory_kinds: frozenset[str] = frozenset()
    # The MCP servers this assistant asks for. The runtime resolves each one
    # against what the deployment admits.
    tool_sources: ToolSourceDeclarations = ()
    # Raises when the caller may not use this assistant. An assistant that
    # declares none is served to any authenticated caller.
    identity_gate: IdentityGate | None = None
    # Chunks written after the turn's graph finishes, keyed by conversation.
    turn_epilogue: TurnEpilogue | None = None


__all__ = [
    "AssistantSpec",
    "GraphFactory",
    "IdentityGate",
    "MockModelFactory",
    "StreamPartHook",
    "TurnContextFactory",
    "TurnContextRequest",
    "TurnEpilogue",
    "TurnStart",
    "TurnStateFactory",
    "turn_input",
]
