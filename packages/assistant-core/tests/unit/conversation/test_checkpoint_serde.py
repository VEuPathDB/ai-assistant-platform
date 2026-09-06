"""A checkpoint must survive a round trip through the runtime's own serializer.

That serializer decodes the types its allowlist declares and nothing else, so a
state type no spec declares fails here rather than on a persisted thread.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.serde.event_hooks import (
    SerdeEvent,
    register_serde_event_listener,
)
from pydantic import BaseModel
from pydantic_ai.ui.vercel_ai.request_types import TextUIPart, ToolApprovalResponded
from tests.synthetic import (
    SYNTHETIC_MODE,
    SYNTHETIC_SITE_ID,
    UsageLedger,
    synthetic_spec,
)

from assistant_core.conversation.serde import (
    CORE_CHECKPOINT_TYPES,
    build_checkpoint_serde,
)
from assistant_core.graph.turn_state import (
    DurableCall,
    DurableTaskResult,
    PendingApproval,
    PendingDurableCall,
    SubAgentApprovalCall,
    SubAgentApprovalPending,
    TurnState,
    UserQuestionAnswer,
)
from assistant_core.memory.schemas import MemoryValue


class UnregisteredState(BaseModel):
    """A state type no spec declared."""

    note: str


def _turn_state() -> TurnState:
    return TurnState(
        conversation_id=UUID("01a011a9-5c65-74b2-8813-215ab5b382fa"),
        user_id=uuid4(),
        site_id=SYNTHETIC_SITE_ID,
        mode=SYNTHETIC_MODE,
        user_prompt="which sites",
        user_parts=[TextUIPart(text="which sites", state="done")],
        turn_total_tokens=51,
        turn_total_cost_usd=Decimal("0.0125"),
        approval_responses={"call_wipe": ToolApprovalResponded(id="a1", approved=True)},
        user_question_answers={
            "call_ask": [UserQuestionAnswer(question_id="q1", prompt="which?")],
        },
        retrieved_memories=[_memory()],
    )


def _memory() -> MemoryValue:
    return MemoryValue(
        kind="knowledge",
        name="a-note",
        summary="one remembered fact",
        content={"detail": "value"},
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


_SAMPLES: dict[type, object] = {
    TextUIPart: TextUIPart(text="hello", state="done"),
    ToolApprovalResponded: ToolApprovalResponded(id="a1", approved=False),
    MemoryValue: _memory(),
    PendingApproval: PendingApproval(
        phase="answer",
        tool_call_id="call_wipe",
        tool_name="wipe_everything",
        tool_args={"target": "everything"},
        prior_messages_json='[{"kind":"request","parts":[]}]',
        sub_agent=SubAgentApprovalPending(
            role="answer",
            approvals=[SubAgentApprovalCall(tool_call_id="call_wipe", tool_name="w")],
        ),
    ),
    PendingDurableCall: PendingDurableCall(
        phase="answer",
        tool_call_id="call_compute",
        tool_name="run_compute",
        tool_args={"method": "DESeq"},
        prior_messages_json='[{"kind":"request","parts":[]}]',
        durable_calls=[
            DurableCall(
                tool_call_id="call_compute",
                tool_name="run_compute",
                args={"method": "DESeq"},
                task_id=UUID("0c6100d2-0000-4000-8000-000000000001"),
                durable_tool_name="run_compute",
            ),
        ],
    ),
    DurableTaskResult: DurableTaskResult(
        task_id=UUID("0c6100d2-0000-4000-8000-000000000001"),
        status="success",
        result={"genesTested": 5511},
    ),
    SubAgentApprovalPending: SubAgentApprovalPending(role="answer"),
    SubAgentApprovalCall: SubAgentApprovalCall(
        tool_call_id="call_wipe",
        tool_name="wipe_everything",
    ),
    UserQuestionAnswer: UserQuestionAnswer(question_id="q1", prompt="which?"),
}


def _strict_roundtrip(value: object, *, declared: tuple[type, ...] = ()) -> object:
    serde = build_checkpoint_serde(declared)
    return serde.loads_typed(serde.dumps_typed(value))


def _events_of(value: object) -> list[SerdeEvent]:
    """What LangGraph reports while the runtime's own serializer decodes."""
    serde = build_checkpoint_serde()
    payload = serde.dumps_typed(value)
    events: list[SerdeEvent] = []
    unregister = register_serde_event_listener(events.append)
    try:
        serde.loads_typed(payload)
    finally:
        unregister()
    return events


def test_every_core_type_has_a_sample_in_this_suite() -> None:
    assert set(CORE_CHECKPOINT_TYPES) == set(_SAMPLES)


@pytest.mark.parametrize("core_type", CORE_CHECKPOINT_TYPES, ids=lambda t: t.__name__)
def test_a_core_type_survives_a_strict_round_trip(core_type: type) -> None:
    sample = _SAMPLES[core_type]

    assert _strict_roundtrip(sample) == sample


def test_the_state_type_a_spec_declares_survives_a_strict_round_trip() -> None:
    spec = synthetic_spec(UsageLedger())
    state = _turn_state()

    restored = _strict_roundtrip(state, declared=spec.checkpoint_types)

    assert restored == state


def test_a_state_type_no_spec_declares_does_not_survive() -> None:
    restored = _strict_roundtrip(UnregisteredState(note="undeclared"))

    assert not isinstance(restored, UnregisteredState)


def test_the_runtime_serializer_decodes_a_declared_type_silently() -> None:
    """A serializer built from the allowlist reports nothing for a listed type."""
    assert _events_of(_memory()) == []
