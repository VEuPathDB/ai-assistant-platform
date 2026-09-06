"""A thread survives its turns: the checkpoint carries what the next turn omits."""

from __future__ import annotations

from tests.synthetic import ADD_PROMPT, PLAIN_PROMPT, SyntheticRuntime

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.persistence.repositories.message import MessagesRepository
from assistant_core.platform.db import async_session_factory


async def test_a_resume_turn_does_not_blank_the_prompt_the_thread_holds(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    await runtime.run(is_resume=True)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    assert snapshot.values["user_prompt"] == PLAIN_PROMPT
    assert snapshot.values["user_parts"][0].text == PLAIN_PROMPT


async def test_the_resumed_turn_answers_from_the_checkpointed_prompt(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    resumed = await runtime.run(is_resume=True)

    deltas = [c["delta"] for c in resumed.chunks if c["type"] == "text-delta"]
    assert deltas == [f"You said: {PLAIN_PROMPT}"]


async def test_a_new_turn_replaces_the_prompt_the_thread_holds(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    await runtime.run(ADD_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    assert snapshot.values["user_prompt"] == ADD_PROMPT


async def test_each_turn_starts_its_accounting_from_zero(
    runtime: SyntheticRuntime,
) -> None:
    first = await runtime.run(PLAIN_PROMPT)
    second = await runtime.run(PLAIN_PROMPT)

    snapshot = await runtime.graph.aget_state(runtime.thread_config())
    charged = [tokens for _user, tokens, _cost in runtime.ledger.charges]
    assert len(charged) == 2
    assert snapshot.values["turn_total_tokens"] == charged[1]
    assert first.turn_message_id != second.turn_message_id


async def test_the_thread_keeps_a_checkpoint_for_every_turn(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)
    await runtime.run(ADD_PROMPT)

    prompts = [
        state.values["user_prompt"]
        async for state in runtime.graph.aget_state_history(runtime.thread_config())
        if "user_prompt" in state.values
    ]

    assert PLAIN_PROMPT in prompts
    assert ADD_PROMPT in prompts


async def test_a_second_turn_appends_to_the_same_thread(
    runtime: SyntheticRuntime,
) -> None:
    first = await runtime.run(PLAIN_PROMPT)
    second = await runtime.run(ADD_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    async with async_session_factory() as session:
        rows = await MessagesRepository(session).list_messages_for_conversation(
            runtime.conversation_id,
        )

    assert [c["type"] for c in logged].count("done") == 2
    assert {row.id for row in rows} == {first.turn_message_id, second.turn_message_id}
