"""The part of a chat-turn job's kwargs the runtime reads back.

The host defers the job and owns the rest of its payload. The stalled-job
sweep reads the two fields it needs to close the stream a killed turn left
open, so a host that shapes its payload differently is refused here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = ["ChatTurnJobArgs", "ChatTurnJobBody", "ChatTurnJobPayload"]
