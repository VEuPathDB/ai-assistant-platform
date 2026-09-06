from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, text

from assistant_core.conversation.empty_parts import EmptyPartGate
from assistant_core.conversation.ui_message_reducer import (
    USER_MESSAGE_CHUNK_TYPE,
    user_message_chunk,
)
from assistant_core.persistence.models import ConversationEvent
from assistant_core.platform.db import async_session_factory


async def append_chunk(
    *,
    conversation_id: UUID,
    chunk: dict[str, Any],
    turn_id: UUID | None = None,
) -> int:
    """Append one chunk to a thread's log and broadcast its cursor.

    A chunk that belongs to no turn, such as a durable task's progress
    between turns, carries no ``turn_id``.
    """
    channel = f"conversation_events:{conversation_id}"
    async with async_session_factory() as session:
        row = ConversationEvent(
            conversation_id=conversation_id,
            turn_id=turn_id,
            chunk=chunk,
        )
        session.add(row)
        await session.flush()
        event_id = row.id
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": channel, "payload": str(event_id)},
        )
        await session.commit()
        return event_id


async def append_user_message_once(
    *,
    conversation_id: UUID,
    turn_id: UUID,
    message_id: UUID,
    parts: list[dict[str, Any]],
) -> int | None:
    """Append the user's envelope unless the log already carries that id.

    A client rebuilds its thread from the log, so one id names one message.
    A turn that replays a logged message adds nothing and returns ``None``.
    """
    async with async_session_factory() as session:
        logged = await session.scalar(
            select(ConversationEvent.id)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.chunk["type"].astext == USER_MESSAGE_CHUNK_TYPE,
                ConversationEvent.chunk["message"]["id"].astext == str(message_id),
            )
            .limit(1),
        )
    if logged is not None:
        return None
    return await append_chunk(
        conversation_id=conversation_id,
        chunk=user_message_chunk(message_id=str(message_id), parts=parts),
        turn_id=turn_id,
    )


class ChatWriter(Protocol):
    """The chunk-sink contract ``run_turn`` drives. ``ChatEventWriter``
    persists to Postgres; devtools supply a console implementation."""

    conversation_id: UUID
    turn_id: UUID

    async def write(self, chunk: dict[str, Any]) -> int: ...


class ChatEventWriter:
    """Persists a chunk row and broadcasts ``NOTIFY`` on the chat channel.

    One writer instance per (conversation, turn). Every ``write(chunk)``
    returns the assigned event id so callers can surface the cursor.
    """

    def __init__(self, *, conversation_id: UUID, turn_id: UUID) -> None:
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self._gate = EmptyPartGate()
        self._last_event_id = 0

    async def write(self, chunk: dict[str, Any]) -> int:
        """Append the chunk and return the event id of the last row written.

        A start chunk the gate holds returns the id of the row before it.
        """
        for admitted in self._gate.admit(chunk):
            self._last_event_id = await append_chunk(
                conversation_id=self.conversation_id,
                chunk=admitted,
                turn_id=self.turn_id,
            )
        return self._last_event_id
