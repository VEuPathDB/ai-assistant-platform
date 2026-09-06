"""A stopped turn spends no further model call and still closes its frame."""

from __future__ import annotations

import asyncio

from tests.synthetic import PLAIN_PROMPT, STOP_PROMPT, STOP_TOOL, SyntheticRuntime

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.persistence.repositories.message import MessagesRepository
from assistant_core.platform.db import async_session_factory


async def test_a_tool_that_stops_the_turn_prevents_the_answer_that_would_follow(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(STOP_PROMPT)

    assert f"tool-{STOP_TOOL}" not in outcome.types()
    assert "tool-output-available" in outcome.types()
    assert "text-delta" not in outcome.types()
    assert outcome.types()[-1] == "data-turn-usage"


async def test_a_stopped_turn_closes_with_the_stopped_marker_then_finish_and_done(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(STOP_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)

    assert [c["type"] for c in logged[-4:]] == [
        "data-turn-stopped",
        "data-turn-status",
        "finish",
        "done",
    ]
    assert logged[-2]["finishReason"] == "other"


async def test_a_stopped_turn_still_accounts_for_what_it_used(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(STOP_PROMPT)

    async with async_session_factory() as session:
        rows = await MessagesRepository(session).list_messages_for_conversation(
            runtime.conversation_id,
        )

    assert runtime.ledger.total_tokens > 0
    assert [row.id for row in rows] == [outcome.turn_message_id]


async def test_a_stop_that_lands_before_the_first_event_still_frames_the_turn(
    runtime: SyntheticRuntime,
) -> None:
    cancel = asyncio.Event()
    cancel.set()

    outcome = await runtime.run(PLAIN_PROMPT, cancel=cancel)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    assert outcome.cancelled
    assert outcome.types() == ["data-turn-status", "finish-step", "data-turn-usage"]
    assert [c["type"] for c in logged[-4:]] == [
        "data-turn-stopped",
        "data-turn-status",
        "finish",
        "done",
    ]
