"""The deferred-tool cycle the runtime owns.

Parking one call with the history that resumes it, reading the user's click,
and re-announcing the parked call. An assistant that selects the call itself
parks it through the same builder and copies its own fields onto the result.
"""

from __future__ import annotations

from uuid import uuid4

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.tools import DeferredToolRequests, ToolDenied
from pydantic_ai.ui.vercel_ai.request_types import ToolApprovalResponded

from assistant_core.graph.approvals import (
    DENIED_WITHOUT_REASON,
    approval_answer,
    approval_results,
    deferred_hint,
    parked_call,
    pending_approval,
    resume_history,
)
from assistant_core.graph.turn_state import (
    SubAgentApprovalCall,
    SubAgentApprovalPending,
)

_CONSULT = ToolCallPart(
    tool_name="consult_user",
    args={"questions": []},
    tool_call_id="call_consult",
)
_DISPATCH = ToolCallPart(
    tool_name="recover_failed_steps",
    args={"reason": "drop s2"},
    tool_call_id="call_dispatch",
)


def _run_history() -> list[ModelRequest | ModelResponse]:
    """A run whose first action is the deferred call."""
    return [
        ModelRequest(parts=[UserPromptPart(content="build it")]),
        ModelResponse(parts=[_CONSULT]),
    ]


def test_a_parked_call_carries_the_call_it_names() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=[])

    assert parked.phase == "agent"
    assert parked.tool_call_id == "call_consult"
    assert parked.tool_name == "consult_user"
    assert parked.tool_args == {"questions": []}


def test_a_parked_call_carries_the_full_run_history() -> None:
    """``new_messages()`` drops the leading request, which pydantic-ai rejects
    on resume, so the park records every message."""
    parked = parked_call(call=_CONSULT, phase="agent", messages=_run_history())

    history = ModelMessagesTypeAdapter.validate_json(parked.prior_messages_json)
    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)


def test_a_parked_call_leaves_the_product_fields_unset() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=[])

    assert parked.sub_agent is None
    assert parked.user_message_id is None


def test_an_assistant_copies_its_own_fields_onto_the_parked_call() -> None:
    """A dispatch the runtime cannot select is parked through the same builder,
    then carries the suspended run and the message it was raised under."""
    stash = SubAgentApprovalPending(
        role="verification",
        approvals=[
            SubAgentApprovalCall(
                tool_call_id="call_inner",
                tool_name="delete_step",
                args={"step_id": "s2"},
            ),
        ],
        messages_json="[]",
    )
    message_id = uuid4()

    parked = parked_call(
        call=_DISPATCH,
        phase="build",
        messages=_run_history(),
    ).model_copy(update={"sub_agent": stash, "user_message_id": message_id})

    assert parked.phase == "build"
    assert parked.tool_call_id == "call_dispatch"
    assert parked.tool_name == "recover_failed_steps"
    assert parked.tool_args == {"reason": "drop s2"}
    assert parked.sub_agent is not None
    assert parked.sub_agent.role == "verification"
    assert parked.sub_agent.approvals[0].tool_call_id == "call_inner"
    assert parked.user_message_id == message_id
    assert parked.prior_messages_json


def test_the_output_selection_parks_the_approval_not_the_call() -> None:
    """A run can defer both an approval and an external call; the runtime waits
    on the approval, because that is the one the user answers."""
    history = _run_history()
    output = DeferredToolRequests(approvals=[_CONSULT], calls=[_DISPATCH])

    parked = pending_approval(output=output, phase="agent", messages=history)

    assert parked == parked_call(call=_CONSULT, phase="agent", messages=history)


def test_an_output_with_no_approval_parks_nothing() -> None:
    output = DeferredToolRequests(calls=[_DISPATCH])

    assert pending_approval(output=output, phase="agent", messages=[]) is None


def test_an_approved_answer_lets_the_call_run() -> None:
    assert approval_answer(ToolApprovalResponded(id="c1", approved=True)) is True


def test_a_denial_without_a_reason_carries_the_default_message() -> None:
    answer = approval_answer(ToolApprovalResponded(id="c1", approved=False))

    assert answer == ToolDenied(message=DENIED_WITHOUT_REASON)


def test_a_denial_keeps_the_reason_the_user_gave() -> None:
    answer = approval_answer(
        ToolApprovalResponded(id="c1", approved=False, reason="not on my data"),
    )

    assert answer == ToolDenied(message="not on my data")


def test_the_results_answer_the_parked_call() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=_run_history())

    results = approval_results(
        parked,
        {"call_consult": ToolApprovalResponded(id="call_consult", approved=True)},
    )

    assert results is not None
    assert results.approvals == {"call_consult": True}


def test_an_unanswered_call_resumes_nothing() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=_run_history())

    assert approval_results(parked, {}) is None


def test_the_resume_history_restores_what_the_park_recorded() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=_run_history())

    restored = resume_history(parked)

    assert len(restored) == 2
    assert isinstance(restored[1], ModelResponse)
    assert restored[1].tool_calls[0].tool_call_id == "call_consult"
    dumped = ModelMessagesTypeAdapter.dump_json(restored).decode()
    assert dumped == parked.prior_messages_json


def test_the_hint_re_announces_the_parked_call_without_sharing_its_args() -> None:
    parked = parked_call(call=_CONSULT, phase="agent", messages=_run_history())

    hint = deferred_hint(parked)
    hint.tool_args["questions"] = ["late edit"]

    assert hint.tool_call_id == "call_consult"
    assert hint.tool_name == "consult_user"
    assert parked.tool_args == {"questions": []}
