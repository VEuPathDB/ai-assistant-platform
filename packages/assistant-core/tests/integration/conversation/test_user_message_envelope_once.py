"""The log carries one `user-message` envelope per message id."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from tests.conftest import seed_thread

from assistant_core.conversation.event_writer import append_user_message_once
from assistant_core.persistence.models import ConversationEvent
from assistant_core.platform.db import async_session_factory


@pytest.fixture
async def thread(patch_app_db_engine: None, db_cleaner: None) -> UUID:
    del patch_app_db_engine, db_cleaner
    conversation_id = uuid4()
    await seed_thread(
        conversation_id=conversation_id,
        user_id=uuid4(),
        site_id="plasmodb",
    )
    return conversation_id


async def _envelopes(conversation_id: UUID) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(ConversationEvent)
                .where(ConversationEvent.conversation_id == conversation_id)
                .order_by(ConversationEvent.id),
            )
        ).all()
    return [row.chunk for row in rows if row.chunk["type"] == "user-message"]


async def test_the_first_write_appends_the_envelope(thread: UUID) -> None:
    message_id = uuid4()

    cursor = await append_user_message_once(
        conversation_id=thread,
        turn_id=message_id,
        message_id=message_id,
        parts=[{"type": "text", "text": "list the kinases"}],
    )

    assert cursor is not None
    logged = await _envelopes(thread)
    assert [chunk["message"]["id"] for chunk in logged] == [str(message_id)]
    assert logged[0]["message"]["parts"] == [
        {"type": "text", "text": "list the kinases"},
    ]


async def test_a_replay_of_the_same_id_appends_nothing(thread: UUID) -> None:
    message_id = uuid4()
    parts: list[dict[str, Any]] = [{"type": "text", "text": "list the kinases"}]
    await append_user_message_once(
        conversation_id=thread,
        turn_id=message_id,
        message_id=message_id,
        parts=parts,
    )

    replay = await append_user_message_once(
        conversation_id=thread,
        turn_id=uuid4(),
        message_id=message_id,
        parts=parts,
    )

    assert replay is None
    logged = await _envelopes(thread)
    assert [chunk["message"]["id"] for chunk in logged] == [str(message_id)]


async def test_another_id_still_appends(thread: UUID) -> None:
    first = uuid4()
    second = uuid4()
    for message_id in (first, second):
        await append_user_message_once(
            conversation_id=thread,
            turn_id=message_id,
            message_id=message_id,
            parts=[{"type": "text", "text": "a question"}],
        )

    logged = await _envelopes(thread)
    assert [chunk["message"]["id"] for chunk in logged] == [str(first), str(second)]


async def test_one_id_is_scoped_to_its_thread(thread: UUID) -> None:
    """A fork copies a parent's ids, so another thread may hold the same id."""
    other = uuid4()
    await seed_thread(conversation_id=other, user_id=uuid4(), site_id="plasmodb")
    message_id = uuid4()
    parts: list[dict[str, Any]] = [{"type": "text", "text": "a question"}]

    await append_user_message_once(
        conversation_id=thread,
        turn_id=message_id,
        message_id=message_id,
        parts=parts,
    )
    cursor = await append_user_message_once(
        conversation_id=other,
        turn_id=message_id,
        message_id=message_id,
        parts=parts,
    )

    assert cursor is not None
    assert len(await _envelopes(other)) == 1
