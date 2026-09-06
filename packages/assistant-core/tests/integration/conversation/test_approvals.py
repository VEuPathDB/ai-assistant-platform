"""The deferred-tool cycle a one-agent assistant runs.

A tool marked approval-required suspends the turn on an approval card, the
thread parks the call, and the next turn carries the user's answer back into
the same run.
"""

from __future__ import annotations

from tests.synthetic import (
    APPROVAL_CALL_ID,
    APPROVAL_PROMPT,
    APPROVAL_TOOL,
    PLAIN_PROMPT,
    SyntheticRuntime,
)

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.conversation.ui_message_reducer import reduce_chunks

AGENT_PHASE = "agent"


def _tool_parts(message: dict[str, object]) -> list[dict[str, object]]:
    parts = message["parts"]
    assert isinstance(parts, list)
    return [p for p in parts if p["type"] == f"tool-{APPROVAL_TOOL}"]


async def _reduced(
    runtime: SyntheticRuntime, turn_message_id: object
) -> dict[str, object]:
    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    return reduce_chunks(logged, default_message_id=str(turn_message_id))


async def test_an_approval_required_tool_reaches_the_user_as_a_card(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(APPROVAL_PROMPT)

    requests = [c for c in outcome.chunks if c["type"] == "tool-approval-request"]
    assert [c["toolCallId"] for c in requests] == [APPROVAL_CALL_ID]
    assert [c for c in outcome.chunks if c["type"] == "error"] == []


async def test_the_suspended_turn_still_closes_with_finish_then_done(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    types = [c["type"] for c in logged]

    assert types.index("tool-approval-request") < types.index("finish")
    assert types[-2:] == ["finish", "done"]
    assert logged[-2]["finishReason"] == "stop"


async def test_the_thread_parks_the_call_the_user_must_answer(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    parked = snapshot.values["pending_approval"]

    assert parked.phase == AGENT_PHASE
    assert parked.tool_call_id == APPROVAL_CALL_ID
    assert parked.tool_name == APPROVAL_TOOL
    assert parked.tool_args == {"target": "everything"}
    assert parked.prior_messages_json


async def test_the_unanswered_tool_did_not_run(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(APPROVAL_PROMPT)

    message = await _reduced(runtime, outcome.turn_message_id)
    parts = _tool_parts(message)

    assert [p["toolCallId"] for p in parts] == [APPROVAL_CALL_ID]
    assert parts[0]["state"] == "approval-requested"
    assert "output" not in parts[0]


async def test_approving_the_call_runs_the_tool_on_the_next_turn(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    resumed = await runtime.answer_approval(APPROVAL_CALL_ID, approved=True)

    outputs = [c for c in resumed.chunks if c["type"] == "tool-output-available"]
    assert [c["toolCallId"] for c in outputs] == [APPROVAL_CALL_ID]
    assert outputs[0]["output"] == "wiped everything"


async def test_the_approved_turn_answers_from_the_tool_it_finally_ran(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    resumed = await runtime.answer_approval(APPROVAL_CALL_ID, approved=True)

    deltas = [c["delta"] for c in resumed.chunks if c["type"] == "text-delta"]
    assert deltas == ["Result: wiped everything."]


async def test_denying_the_call_reaches_the_client_as_a_denial(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    resumed = await runtime.answer_approval(
        APPROVAL_CALL_ID,
        approved=False,
        reason="not on my data",
    )

    denials = [c for c in resumed.chunks if c["type"] == "tool-output-denied"]
    assert [c["toolCallId"] for c in denials] == [APPROVAL_CALL_ID]
    assert [c for c in resumed.chunks if c["type"] == "tool-output-available"] == []


async def test_an_answered_approval_leaves_the_thread_unblocked(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    await runtime.answer_approval(APPROVAL_CALL_ID, approved=False)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    assert snapshot.values["pending_approval"] is None


async def test_a_new_message_instead_of_an_answer_drops_the_card(
    runtime: SyntheticRuntime,
) -> None:
    """The user asked for something else, so the turn is a fresh one and the
    call the user never approved is not carried forward."""
    await runtime.run(APPROVAL_PROMPT)

    followed = await runtime.run(PLAIN_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    deltas = [c["delta"] for c in followed.chunks if c["type"] == "text-delta"]
    assert snapshot.values["pending_approval"] is None
    assert deltas == [f"You said: {PLAIN_PROMPT}"]
