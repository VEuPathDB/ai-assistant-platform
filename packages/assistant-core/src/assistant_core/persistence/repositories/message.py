from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import Message
from assistant_core.persistence.repositories._message_metadata import MessageMetadata


class MessagesRepository:
    """Persistence for AI-SDK v6 ``UIMessage`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_message(
        self,
        *,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        metadata: dict[str, Any],
    ) -> None:
        stmt = (
            pg_insert(Message)
            .values(
                id=message_id,
                conversation_id=conversation_id,
                role=role,
                metadata_=metadata,
            )
            .on_conflict_do_nothing(index_elements=[Message.id])
        )
        await self.session.execute(stmt)

    async def upsert_message(
        self,
        *,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        metadata: dict[str, Any],
    ) -> None:
        stmt = (
            pg_insert(Message)
            .values(
                id=message_id,
                conversation_id=conversation_id,
                role=role,
                metadata_=metadata,
            )
            .on_conflict_do_update(
                index_elements=[Message.id],
                set_={Message.metadata_: metadata},
            )
        )
        await self.session.execute(stmt)

    async def list_messages_for_conversation(
        self, conversation_id: UUID
    ) -> list[Message]:
        """Return messages for a chat, oldest first."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_usage_for_conversation(
        self,
        conversation_id: UUID,
    ) -> tuple[int, Decimal]:
        """Sum ``metadata.usage.{totalTokens,costUsd}`` across all messages."""
        stmt = select(Message.metadata_).where(
            Message.conversation_id == conversation_id,
        )
        result = await self.session.execute(stmt)
        total_tokens = 0
        total_cost = Decimal(0)
        for (meta,) in result.all():
            usage = MessageMetadata.model_validate(meta).usage
            if usage is None:
                continue
            total_tokens += usage.total_tokens
            total_cost += usage.cost_decimal()
        return total_tokens, total_cost

    async def mark_turn_completed(self, message_id: UUID) -> None:
        """Flag an assistant message as the verification-complete row of its turn.

        The autowrite path reads ``metadata.turnCompleted == true`` on
        verification messages to count successful turns without consulting
        the in-flight pipeline state.
        """
        message = await self.session.get(Message, message_id)
        if message is None:
            return
        meta = MessageMetadata.model_validate(message.metadata_)
        meta.turn_completed = True
        message.metadata_ = meta.model_dump(by_alias=True, exclude_none=True)
