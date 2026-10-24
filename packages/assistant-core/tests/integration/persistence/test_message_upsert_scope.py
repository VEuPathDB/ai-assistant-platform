from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from structlog.testing import capture_logs
from tests.conftest import seed_thread

from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.errors import MessageOwnedElsewhereError
from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_message import write_turn_message
from assistant_core.graph.turn_state import TurnState
from assistant_core.persistence.models import Conversation, Message
from assistant_core.persistence.repositories.message import MessagesRepository
from assistant_core.platform.db import async_session_factory

PARENT_METADATA: dict[str, object] = {
    "usage": {"totalTokens": 120, "costUsd": "0.01"},
}
BRANCH_METADATA: dict[str, object] = {
    "usage": {"totalTokens": 999, "costUsd": "0.75"},
}


async def _threads() -> tuple[UUID, UUID]:
    owner, parent, branch = uuid4(), uuid4(), uuid4()
    await seed_thread(conversation_id=parent, user_id=owner, site_id="plasmodb")
    async with async_session_factory() as session:
        session.add(Conversation(id=branch, user_id=owner, site_id="plasmodb"))
        await session.commit()
    return parent, branch


async def _upsert(
    message_id: UUID,
    conversation_id: UUID,
    metadata: dict[str, object],
) -> None:
    async with async_session_factory() as session:
        await MessagesRepository(session).upsert_message(
            message_id=message_id,
            conversation_id=conversation_id,
            role="assistant",
            metadata=metadata,
        )
        await session.commit()


async def _row(message_id: UUID) -> tuple[UUID, dict[str, object]]:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(Message.conversation_id, Message.metadata_).where(
                    Message.id == message_id,
                ),
            )
        ).one()
    return row[0], row[1]


@pytest.mark.usefixtures("patch_app_db_engine", "db_cleaner")
async def test_an_upsert_naming_another_conversation_leaves_the_row_alone() -> None:
    parent, branch = await _threads()
    message_id = uuid4()
    await _upsert(message_id, parent, PARENT_METADATA)

    with pytest.raises(MessageOwnedElsewhereError) as refused:
        await _upsert(message_id, branch, BRANCH_METADATA)

    assert refused.value.message_id == message_id
    assert refused.value.conversation_id == branch
    assert await _row(message_id) == (parent, PARENT_METADATA)


@pytest.mark.usefixtures("patch_app_db_engine", "db_cleaner")
async def test_an_upsert_in_its_own_conversation_replaces_the_metadata() -> None:
    parent, _ = await _threads()
    message_id = uuid4()
    await _upsert(message_id, parent, PARENT_METADATA)

    await _upsert(message_id, parent, BRANCH_METADATA)

    assert await _row(message_id) == (parent, BRANCH_METADATA)


@pytest.mark.usefixtures("patch_app_db_engine", "db_cleaner")
async def test_a_turn_naming_another_conversation_s_message_writes_nothing() -> None:
    parent, branch = await _threads()
    message_id = uuid4()
    await _upsert(message_id, parent, PARENT_METADATA)
    writer = ChatEventWriter(conversation_id=branch, turn_id=message_id)
    for chunk in (
        {"type": "start", "messageId": str(message_id)},
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "Noted."},
        {"type": "text-end", "id": "t1"},
        {"type": "finish"},
    ):
        await writer.write(chunk)
    state = TurnState(
        conversation_id=branch,
        user_id=uuid4(),
        site_id="plasmodb",
        mode="strategy",
        turn_message_id=message_id,
        turn_total_tokens=999,
    )
    context = TurnContext(
        site_id="plasmodb",
        user_id=state.user_id,
        db_session_factory=async_session_factory,
        cancel_event=asyncio.Event(),
    )

    with capture_logs() as logs:
        written = await write_turn_message(context=context, state=state)

    assert written is None
    assert await _row(message_id) == (parent, PARENT_METADATA)
    assert [
        (entry["event"], entry["message_id"], entry["error"])
        for entry in logs
        if entry["log_level"] == "warning"
    ] == [
        ("failed to write turn message", str(message_id), "MessageOwnedElsewhereError"),
    ]
