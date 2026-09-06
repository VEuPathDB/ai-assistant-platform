"""A thread's own messages reach the next turn's model, through the checkpoint."""

from __future__ import annotations

from pydantic_ai.messages import ModelRequest, ModelResponse
from tests.synthetic import (
    ADD_PROMPT,
    APPROVAL_CALL_ID,
    APPROVAL_PROMPT,
    PLAIN_PROMPT,
    RECALL_PREFIX,
    RECALL_PROMPT,
    SyntheticRuntime,
)

from assistant_core.graph.thread_history import thread_history


def _deltas(chunks: list[dict[str, object]]) -> list[object]:
    return [c["delta"] for c in chunks if c["type"] == "text-delta"]


async def test_the_second_turn_answers_from_the_first(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(ADD_PROMPT)

    outcome = await runtime.run(RECALL_PROMPT)

    assert _deltas(outcome.chunks) == [f"{RECALL_PREFIX}{ADD_PROMPT}"]


async def test_the_checkpoint_carries_the_thread_s_messages(
    runtime: SyntheticRuntime,
) -> None:
    """The messages survive the real serializer, and end on the turn's answer."""
    await runtime.run(PLAIN_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    messages = thread_history(snapshot.values["thread_messages_json"])

    assert messages is not None
    assert [type(message) for message in messages] == [ModelRequest, ModelResponse]
    assert isinstance(messages[1], ModelResponse)
    assert not messages[1].tool_calls


async def test_a_parked_call_is_not_carried_into_the_next_turn(
    runtime: SyntheticRuntime,
) -> None:
    """A turn that waits on an approval leaves the thread at the last answer,
    because pydantic-ai refuses a new prompt over an unprocessed call."""
    await runtime.run(PLAIN_PROMPT)

    await runtime.run(APPROVAL_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    messages = thread_history(snapshot.values["thread_messages_json"])
    assert messages is not None
    assert snapshot.values["pending_approval"].tool_call_id == APPROVAL_CALL_ID
    assert [type(message) for message in messages] == [ModelRequest, ModelResponse]


async def test_an_answered_card_leaves_the_call_and_its_result_on_the_thread(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(APPROVAL_PROMPT)

    await runtime.answer_approval(APPROVAL_CALL_ID, approved=True)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    messages = thread_history(snapshot.values["thread_messages_json"])
    assert messages is not None
    calls = [
        call.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for call in message.tool_calls
    ]
    assert calls == [APPROVAL_CALL_ID]
