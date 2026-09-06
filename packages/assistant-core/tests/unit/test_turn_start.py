"""What a turn puts into the graph, and what it deliberately leaves out."""

from __future__ import annotations

from uuid import uuid4

from pydantic_ai.ui.vercel_ai.request_types import ToolApprovalResponded
from tests.synthetic import PLAIN_PROMPT, SYNTHETIC_MODE, SYNTHETIC_SITE_ID

from assistant_core.graph.turn_state import TurnState
from assistant_core.spec import TurnStart, turn_input


def _start(*, is_resume: bool) -> TurnStart:
    return TurnStart(
        conversation_id=uuid4(),
        user_id=uuid4(),
        site_id=SYNTHETIC_SITE_ID,
        mode=SYNTHETIC_MODE,
        turn_message_id=uuid4(),
        turn_start_event_id=7,
        is_resume=is_resume,
        user_message_id=None if is_resume else uuid4(),
        user_prompt="" if is_resume else PLAIN_PROMPT,
    )


def test_a_first_turn_sets_the_prompt_fields() -> None:
    kwargs = _start(is_resume=False).state_kwargs()

    assert kwargs["user_prompt"] == PLAIN_PROMPT
    assert kwargs["user_message_id"] is not None
    assert [part.text for part in kwargs["user_parts"]] == [PLAIN_PROMPT]


def test_a_resume_turn_names_no_prompt_field_at_all() -> None:
    kwargs = _start(is_resume=True).state_kwargs()

    assert "user_prompt" not in kwargs
    assert "user_message_id" not in kwargs
    assert "user_parts" not in kwargs


def test_a_turn_carries_the_approval_answers_it_was_given() -> None:
    answer = ToolApprovalResponded(id="approval-1", approved=True)
    start = _start(is_resume=True).model_copy(
        update={"approval_responses": {"call_wipe": answer}},
    )

    state = TurnState(**start.state_kwargs())

    assert state.approval_responses["call_wipe"].approved is True
    assert "approval_responses" in turn_input(state)


def test_the_graph_update_carries_only_the_fields_the_turn_set() -> None:
    update = turn_input(TurnState(**_start(is_resume=True).state_kwargs()))

    assert "user_prompt" not in update
    assert update["turn_total_tokens"] == 0
    assert update["turn_start_event_id"] == 7
