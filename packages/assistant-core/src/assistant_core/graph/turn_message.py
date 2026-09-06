"""The assistant message a finished turn leaves behind.

The parts live in the durable event log; this row carries the turn's metadata
and its usage totals, which is what conversation-level accounting reads.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.conversation.ui_message_reducer import reduce_chunks
from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_state import TurnState
from assistant_core.persistence.repositories._message_metadata import MessageMetadata
from assistant_core.persistence.repositories.message import MessagesRepository
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)


def _build_metadata(
    *,
    state: TurnState,
    total_tokens: int,
    cost_usd: Decimal,
) -> dict[str, Any]:
    return MessageMetadata.model_validate(
        {
            "traceId": state.turn_trace_id,
            "createdAt": state.turn_created_at,
            "siteId": state.site_id,
            "mode": state.mode,
            "usage": {
                "totalTokens": total_tokens,
                "costUsd": str(cost_usd),
            },
        },
    ).model_dump(by_alias=True, exclude_none=True)


async def write_turn_message(
    *,
    context: TurnContext,
    state: TurnState,
) -> UUID | None:
    """Persist the assistant message once the turn's chunks are in the log.

    Returns ``None`` when the turn produced no parts, and when the write
    fails: a missing metadata row must not fail a turn the user already read.
    """
    try:
        _, chunks = await fetch_chunks_after(
            state.conversation_id,
            state.turn_start_event_id,
        )
        if not chunks:
            return None
        msg = reduce_chunks(chunks, default_message_id=str(state.turn_message_id))
        if not msg["parts"]:
            return None
        message_id = UUID(msg.get("id") or str(state.turn_message_id))
        async with context.db_session_factory() as session:
            await MessagesRepository(session).upsert_message(
                message_id=message_id,
                conversation_id=state.conversation_id,
                role="assistant",
                metadata=_build_metadata(
                    state=state,
                    total_tokens=state.turn_total_tokens,
                    cost_usd=state.turn_total_cost_usd,
                ),
            )
            await session.commit()
    except SQLAlchemyError:
        logger.warning(
            "failed to write turn message",
            conversation_id=str(state.conversation_id),
        )
        return None
    return message_id


__all__ = ["write_turn_message"]
