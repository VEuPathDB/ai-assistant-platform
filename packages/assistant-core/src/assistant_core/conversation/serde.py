"""Checkpoint serializer with an explicit msgpack type allowlist.

Every type that reaches a checkpoint must be on the allowlist. The serializer
returns anything else as a raw payload, so an undeclared state type is a
refusal here and never an unresumable conversation after a LangGraph upgrade.

Core types are listed here. An assistant declares its own state types on its
``AssistantSpec``; one checkpoint table serves every assistant, so callers
pass the union.
"""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic_ai.ui.vercel_ai.request_types import (
    TextUIPart,
    ToolApprovalResponded,
)

from assistant_core.graph.turn_state import (
    DurableTaskResult,
    PendingApproval,
    PendingDurableCall,
    SubAgentApprovalCall,
    SubAgentApprovalPending,
    UserQuestionAnswer,
)
from assistant_core.memory.schemas import MemoryValue

__all__ = [
    "CORE_CHECKPOINT_TYPES",
    "build_checkpoint_serde",
    "checkpoint_types",
]


CORE_CHECKPOINT_TYPES: tuple[type, ...] = (
    TextUIPart,
    ToolApprovalResponded,
    MemoryValue,
    PendingApproval,
    PendingDurableCall,
    DurableTaskResult,
    SubAgentApprovalPending,
    SubAgentApprovalCall,
    UserQuestionAnswer,
)


def checkpoint_types(assistant_types: tuple[type, ...] = ()) -> tuple[type, ...]:
    """The core types plus the state types the assistants declare."""
    return (*CORE_CHECKPOINT_TYPES, *(t for t in assistant_types))


def build_checkpoint_serde(
    assistant_types: tuple[type, ...] = (),
) -> JsonPlusSerializer:
    """A serializer that decodes allowlisted state and refuses the rest.

    The allowlist binds at construction; a serializer built without one allows
    every module and cannot be narrowed afterwards.
    """
    return JsonPlusSerializer(
        allowed_msgpack_modules=checkpoint_types(assistant_types),
    )
