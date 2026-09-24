"""The durable-task row, the job that runs it, and the thread's active work."""

from __future__ import annotations

from asyncio import shield
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import BackgroundTask
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.context import phase_overrides_ctx
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.app import durable_task_queue, task_app
from assistant_core.tasks.declaration import DurableTool
from assistant_core.tasks.payloads import DurableTaskPayload

_ACTIVE_TASK_STATUSES: frozenset[str] = frozenset({"pending", "running", "resuming"})


async def has_active_task(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> bool:
    """Whether the thread has a pending, running or resuming durable task.

    A host-started task has no call a turn waits on, so it never counts.
    """
    found = await session.scalar(
        select(BackgroundTask.id)
        .where(
            BackgroundTask.conversation_id == conversation_id,
            BackgroundTask.user_id == user_id,
            BackgroundTask.status.in_(_ACTIVE_TASK_STATUSES),
            BackgroundTask.tool_call_id.is_not(None),
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
    tool_call_id: str | None,
    estimated_duration_seconds: int,
) -> UUID:
    """Create a ``background_tasks`` row and return its id.

    The row records the calling turn's per-role picks, because the turn that
    answers the task opens after the request that made them is gone.
    ``tool_call_id`` is None for a task the host starts.
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


async def discard_background_task(*, task_id: UUID) -> None:
    """Remove the row of a call whose job the queue did not accept."""
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    await repo.delete(task_id=task_id)


async def defer_durable_job(
    tool: DurableTool,
    *,
    task_id: UUID,
    thread_id: UUID,
    args: dict[str, Any],
    lock: str,
) -> None:
    """Defer the job that runs one task row, under ``lock``.

    A job the queue does not take leaves no row behind.
    """
    job = task_app().configure_task(
        name=tool.job_name,
        queue=durable_task_queue(),
        lock=lock,
    )
    payload = DurableTaskPayload.from_context(
        task_id=task_id,
        thread_id=thread_id,
        args=args,
    )
    try:
        await job.defer_async(**payload.model_dump(mode="json", by_alias=True))
    except BaseException as refusal:
        await _discard(task_id, refusal)
        raise


async def _discard(task_id: UUID, refusal: BaseException) -> None:
    """Remove the row of a task the queue did not take the job for.

    The removal is shielded, so a cancelled defer strands nothing, and a
    removal that fails rides the refusal instead of replacing it.
    """
    try:
        await shield(discard_background_task(task_id=task_id))
    except (OSError, SQLAlchemyError) as failure:
        refusal.add_note(f"the durable task row was not removed: {failure}")


__all__ = [
    "create_background_task",
    "defer_durable_job",
    "discard_background_task",
    "has_active_task",
]
