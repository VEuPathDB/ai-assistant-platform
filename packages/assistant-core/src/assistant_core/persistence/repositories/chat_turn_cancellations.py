"""Stop requests for a turn, and the notification that wakes its worker."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import ChatTurnCancellation

SessionFactory = Callable[[], AsyncSession]


class ChatTurnCancellationRepository:
    def __init__(self, *, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def request_cancel(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
    ) -> None:
        stmt = (
            pg_insert(ChatTurnCancellation)
            .values(conversation_id=conversation_id, turn_id=turn_id)
            .on_conflict_do_nothing(
                index_elements=["conversation_id", "turn_id"],
            )
        )
        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.execute(
                text(
                    "SELECT pg_notify(:channel, :payload)",
                ),
                {
                    "channel": f"chat_turn_cancel:{conversation_id}",
                    "payload": str(turn_id),
                },
            )
            await session.commit()

    async def is_cancelled(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
    ) -> bool:
        stmt = select(ChatTurnCancellation).where(
            ChatTurnCancellation.conversation_id == conversation_id,
            ChatTurnCancellation.turn_id == turn_id,
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
