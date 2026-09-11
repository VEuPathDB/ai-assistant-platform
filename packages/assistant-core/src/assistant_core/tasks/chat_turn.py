"""Deferring one chat turn, and the part of its kwargs the runtime reads back.

The host owns the rest of the payload. The stalled-job sweep reads the two
fields it needs to close the stream a killed turn left open, so a payload
without them is refused before the job exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from assistant_core.tasks.app import task_app
from assistant_core.tasks.names import CHAT_TURN_QUEUE, CHAT_TURN_TASK


class ChatTurnJobBody(BaseModel):
    """The thread a chat-turn job names, in either casing."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    conversation_id: UUID = Field(alias="conversationId")


class ChatTurnJobPayload(BaseModel):
    """The turn a chat-turn job writes, in either casing."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    turn_id: UUID = Field(alias="turnId")
    body: ChatTurnJobBody


class ChatTurnJobArgs(BaseModel):
    """The kwargs a ``chat_turn:run`` job stores, as the runtime reads them."""

    model_config = ConfigDict(extra="ignore")

    payload: ChatTurnJobPayload


async def defer_chat_turn(
    *,
    conversation_id: UUID,
    payload: Mapping[str, JsonValue],
) -> int:
    """Defer this thread's next turn onto the host's queue.

    Every turn of one thread writes one checkpoint thread, so the lock keeps
    two workers from running two turns of it together.
    """
    ChatTurnJobPayload.model_validate(payload)
    job = task_app().configure_task(
        name=CHAT_TURN_TASK,
        queue=CHAT_TURN_QUEUE,
        lock=str(conversation_id),
    )
    deferred: int = await job.defer_async(payload=dict(payload))
    return deferred


__all__ = [
    "ChatTurnJobArgs",
    "ChatTurnJobBody",
    "ChatTurnJobPayload",
    "defer_chat_turn",
]
