"""The per-turn resources and dependency container the runtime owns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from assistant_core.capabilities.repetition_guard import ToolRepetitionGuard
from assistant_core.graph.turn_state import DurableDeferral
from assistant_core.memory.schemas import MemoryValue
from assistant_core.platform.db import DBSessionFactory
from assistant_core.platform.types import ReasoningEffort


@dataclass(frozen=True, kw_only=True)
class TurnContext:
    # Non-serializable per-turn resources passed via
    # ``graph.astream(..., context=ctx)``; never checkpointed.

    site_id: str
    user_id: UUID
    db_session_factory: DBSessionFactory
    cancel_event: asyncio.Event
    memory_store: AsyncPostgresStore | None = None
    # Keyed by the product's own role names; the runtime never reads them.
    phase_models: dict[str, str] = field(default_factory=dict)
    phase_reasoning: dict[str, ReasoningEffort] = field(default_factory=dict)


class GuardedDeps(Protocol):
    """What a turn graph needs from an agent's deps to drive one run."""

    tool_repetition_guard: ToolRepetitionGuard
    durable_deferrals: dict[str, DurableDeferral]


class AssistantDeps(BaseModel):
    # Resource fields use ``SkipValidation`` so tests can inject mock
    # instances without tripping Pydantic's isinstance check.

    model_config = ConfigDict(arbitrary_types_allowed=True)

    site_id: str
    user_id: UUID | None = None
    conversation_id: UUID | None = None
    db_session_factory: SkipValidation[DBSessionFactory] | None = None
    memory_store: SkipValidation[AsyncPostgresStore] | None = None
    cancel_event: SkipValidation[asyncio.Event] | None = None
    retrieved_memories: list[MemoryValue] = Field(default_factory=list)
    tool_repetition_guard: ToolRepetitionGuard = Field(
        default_factory=ToolRepetitionGuard,
    )
    # Durable calls this run handed to a worker, keyed by their tool call id.
    durable_deferrals: dict[str, DurableDeferral] = Field(default_factory=dict)
