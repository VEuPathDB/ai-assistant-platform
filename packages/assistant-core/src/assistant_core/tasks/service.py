"""The durable-task row a deferring turn writes, and the thread's active work."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import BackgroundTask
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.context import phase_overrides_ctx
from assistant_core.platform.db import async_session_factory

_ACTIVE_TASK_STATUSES: frozenset[str] = frozenset({"pending", "running", "resuming"})


async def has_active_task(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> bool:
    """Whether the thread has a pending, running or resuming durable task."""
    found = await session.scalar(
        select(BackgroundTask.id)
        .where(
            BackgroundTask.conversation_id == conversation_id,
            BackgroundTask.user_id == user_id,
            BackgroundTask.status.in_(_ACTIVE_TASK_STATUSES),
        )
        .limit(1),
    )
    return found is not None


async def create_background_task(
    *,
    conversation_id: UUID,
    user_id: UUID,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str,
    estimated_duration_seconds: int,
) -> UUID:
    """Create a ``background_tasks`` row and return its id.

    The row records the calling turn's per-role picks, because the turn that
    answers the task opens after the request that made them is gone.
    """
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    return await repo.create(
        task=NewBackgroundTask(
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name=tool_name,
            args=args,
            tool_call_id=tool_call_id,
            estimated_duration_seconds=estimated_duration_seconds,
            phase_overrides=phase_overrides_ctx.get().model_dump(mode="json"),
        ),
    )


__all__ = ["create_background_task", "has_active_task"]
