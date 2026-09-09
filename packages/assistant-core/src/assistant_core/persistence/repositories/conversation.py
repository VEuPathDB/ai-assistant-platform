"""Data access for chat threads: create, read, list, dismiss, restore, delete."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import Conversation
from assistant_core.platform.context import calling_application

# The name a thread takes when its creator names none.
DEFAULT_CONVERSATION_NAME = "New Conversation"

_DESCENDANTS = text(
    """
    WITH RECURSIVE descendants(id) AS (
        SELECT id FROM conversations WHERE id = :id
        UNION ALL
        SELECT c.id FROM conversations c
        JOIN descendants d ON c.parent_conversation_id = d.id
    )
    DELETE FROM conversations WHERE id IN (SELECT id FROM descendants)
    """,
)


class ConversationRepository:
    """Data access for chat threads.

    Every listing is scoped to the user under the calling application; a lookup
    by id is not, because the ownership helpers decide that case.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def deduplicate_name(
        self,
        user_id: UUID,
        site_id: str,
        name: str,
        *,
        exclude_conversation_id: UUID | None = None,
    ) -> str:
        """A name no other thread of this user and site holds.

        A taken name gets a numeric suffix.
        """
        query = select(Conversation.name).where(
            Conversation.user_id == user_id,
            Conversation.application_id == calling_application(),
            Conversation.site_id == site_id,
        )
        if exclude_conversation_id is not None:
            query = query.where(Conversation.id != exclude_conversation_id)
        result = await self.session.execute(query)
        existing: set[str] = {row[0] for row in result.all() if row[0]}

        if name not in existing:
            return name

        i = 1
        while f"{name} ({i})" in existing:
            i += 1
        return f"{name} ({i})"

    async def create(
        self,
        user_id: UUID,
        site_id: str,
        *,
        conversation_id: UUID | None = None,
        name: str = "",
    ) -> Conversation:
        """Create a thread with a deduplicated name.

        A caller can supply the id so the client and the server use one value.
        """
        resolved_name = await self.deduplicate_name(
            user_id,
            site_id,
            name or DEFAULT_CONVERSATION_NAME,
        )
        conversation = Conversation(
            id=conversation_id or uuid4(),
            user_id=user_id,
            site_id=site_id,
            name=resolved_name,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def delete(
        self,
        conversation_id: UUID,
        *,
        cascade: bool = False,
    ) -> None:
        """Delete a thread.

        Without ``cascade`` the direct children move up to the deleted node's
        parent. With ``cascade`` the whole subtree goes.
        """
        if cascade:
            await self.session.execute(_DESCENDANTS, {"id": str(conversation_id)})
            await self.session.flush()
            return

        deleted = await self.session.scalar(
            select(Conversation).where(Conversation.id == conversation_id),
        )
        if deleted is not None:
            await self.session.execute(
                update(Conversation)
                .where(Conversation.parent_conversation_id == conversation_id)
                .values(
                    parent_conversation_id=deleted.parent_conversation_id,
                    parent_message_id=deleted.parent_message_id,
                ),
            )
        await self.session.execute(
            delete(Conversation).where(Conversation.id == conversation_id),
        )
        await self.session.flush()

    def _owned_threads(
        self,
        user_id: UUID,
        *,
        site_id: str | None,
        limit: int,
    ) -> Select[tuple[Conversation]]:
        """The threads of this user under the calling application.

        The statement carries no dismissal filter and no order: a listing adds
        both.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .where(Conversation.application_id == calling_application())
            .execution_options(populate_existing=True)
            .limit(limit)
        )
        if site_id:
            stmt = stmt.where(Conversation.site_id == site_id)
        return stmt

    async def list_active(
        self,
        user_id: UUID,
        *,
        site_id: str | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        """Threads that are not dismissed, most recently updated first."""
        stmt = (
            self._owned_threads(user_id, site_id=site_id, limit=limit)
            .where(Conversation.dismissed_at.is_(None))
            .order_by(Conversation.updated_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_dismissed(
        self,
        user_id: UUID,
        *,
        site_id: str | None = None,
        limit: int = 50,
    ) -> list[Conversation]:
        """Dismissed threads, most recently dismissed first."""
        stmt = (
            self._owned_threads(user_id, site_id=site_id, limit=limit)
            .where(Conversation.dismissed_at.is_not(None))
            .order_by(Conversation.dismissed_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_thread(
        self,
        conversation_id: UUID,
        *,
        name: str | None = None,
        touch_updated_at: bool = False,
    ) -> str | None:
        """Write the thread's own columns; report the name that was stored.

        A new name is deduplicated for the thread's owner and site, so the
        caller learns what the row now holds.
        """
        values: dict[str, Any] = {}
        if touch_updated_at:
            values["updated_at"] = datetime.now(UTC)
        stored_name = None
        if name is not None:
            owner = (
                await self.session.execute(
                    select(Conversation.user_id, Conversation.site_id).where(
                        Conversation.id == conversation_id,
                    ),
                )
            ).one_or_none()
            # A thread that is already gone takes the name unchanged: the
            # update below matches no row.
            stored_name = name
            if owner is not None:
                stored_name = await self.deduplicate_name(
                    owner.user_id,
                    owner.site_id,
                    name,
                    exclude_conversation_id=conversation_id,
                )
            values["name"] = stored_name

        if values:
            await self.session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(**values)
            )
        return stored_name

    async def dismiss(self, conversation_id: UUID) -> None:
        """Mark a thread as dismissed, which hides it from the main list."""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(dismissed_at=datetime.now(UTC))
        )
        await self.session.flush()

    async def restore(self, conversation_id: UUID) -> None:
        """Restore a dismissed thread."""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(dismissed_at=None)
        )
        await self.session.flush()
