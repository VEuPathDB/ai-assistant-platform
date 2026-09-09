"""Thread lookup and ownership.

A thread belongs to a user under one application, so both must match before a
caller reaches it.
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.errors import (
    ConversationForbiddenError,
    ConversationNotFoundError,
)
from assistant_core.persistence.models import Conversation
from assistant_core.persistence.repositories.conversation import ConversationRepository
from assistant_core.platform.context import calling_application
from assistant_core.platform.db import async_session_factory


class ConversationLookup(Protocol):
    """The one read the ownership helpers make on a thread store."""

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None: ...


def owned_by_caller(conversation: Conversation, user_id: UUID) -> bool:
    """Whether the thread belongs to this user under this application."""
    return (
        conversation.user_id == user_id
        and conversation.application_id == calling_application()
    )


async def get_conversation(
    repo: ConversationLookup,
    conversation_id: UUID,
) -> Conversation:
    """The thread, whoever owns it. Raises when there is no such row."""
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)
    return conversation


async def get_owned_conversation(
    repo: ConversationLookup,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation:
    """The caller's thread, telling a non-owner that the thread exists."""
    conversation = await get_conversation(repo, conversation_id)
    if not owned_by_caller(conversation, user_id):
        raise ConversationForbiddenError(conversation_id)
    return conversation


async def get_visible_conversation(
    repo: ConversationLookup,
    conversation_id: UUID,
    user_id: UUID,
) -> Conversation:
    """The caller's thread, hiding its existence from everybody else.

    A non-owner gets the same error as a caller naming an id that never
    existed, so the id itself tells them nothing.
    """
    conversation = await repo.get_by_id(conversation_id)
    if conversation is None or not owned_by_caller(conversation, user_id):
        raise ConversationNotFoundError(conversation_id)
    return conversation


async def assert_owner(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    """Raise unless ``user_id`` owns ``conversation_id``, hiding existence."""
    await get_visible_conversation(
        ConversationRepository(session),
        conversation_id,
        user_id,
    )


async def conversation_assistant_id(conversation_id: UUID) -> str | None:
    """The assistant that answers a thread, or None if it is gone.

    The row is the source of truth: a thread never changes assistant, so a
    later turn resolves the same architecture the first one ran.
    """
    async with async_session_factory() as session:
        assistant_id: str | None = await session.scalar(
            select(Conversation.assistant_id).where(
                Conversation.id == conversation_id,
            ),
        )
    return assistant_id


async def conversation_owner_id(conversation_id: UUID) -> UUID | None:
    """The account a thread belongs to, or None if it is gone.

    A worker job that opens a turn on a thread acts as its owner.
    """
    async with async_session_factory() as session:
        user_id: UUID | None = await session.scalar(
            select(Conversation.user_id).where(
                Conversation.id == conversation_id,
            ),
        )
    return user_id


async def conversation_application_id(conversation_id: UUID) -> str | None:
    """The application that holds a thread, or None if it is gone.

    The row is the source of truth a worker job reads to run as the right
    application.
    """
    async with async_session_factory() as session:
        application_id: str | None = await session.scalar(
            select(Conversation.application_id).where(
                Conversation.id == conversation_id,
            ),
        )
    return application_id
