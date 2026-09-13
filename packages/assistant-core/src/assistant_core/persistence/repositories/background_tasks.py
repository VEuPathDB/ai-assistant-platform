"""Reads and writes on the durable-task row.

A worker holds no long-lived session, so every transition opens its own unit
of work through the factory the caller supplies.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, text, update

from assistant_core.persistence.models import BackgroundTask
from assistant_core.platform.db import DBSessionFactory

ACTIVE_TASK_STATES = ("pending", "running", "resuming", "result_ready")
"""The statuses of a task the worker has not finished with."""

REPORTED_TASK_STATES = ("result_ready", "resuming", "complete", "failed")
"""The statuses of a task whose outcome the row already records."""


class TaskOutcome(BaseModel):
    """The outcome one finished ``background_tasks`` row records."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

    @field_validator("result", mode="before")
    @classmethod
    def _absent_result_is_empty(cls, value: object) -> object:
        return {} if value is None else value

    @field_validator("error", mode="before")
    @classmethod
    def _absent_error_is_empty(cls, value: object) -> object:
        return "" if value is None else value

    @property
    def failed(self) -> bool:
        """Whether the tool reported a failure rather than a result."""
        return self.status == "failed"


class NewBackgroundTask(BaseModel):
    """The durable call a turn defers, as the row records it.

    ``phase_overrides`` is the deferring turn's per-role picks, so the turn
    that answers the call resolves the same models.
    """

    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    user_id: UUID
    tool_name: str
    tool_call_id: str
    args: dict[str, Any]
    estimated_duration_seconds: int
    phase_overrides: dict[str, Any]


class BackgroundTaskRepository:
    """Create and transition ``background_tasks`` rows."""

    def __init__(self, *, session_factory: DBSessionFactory) -> None:
        self._session_factory = session_factory

    async def create(self, *, task: NewBackgroundTask) -> UUID:
        task_id = uuid4()
        async with self._session_factory() as session:
            session.add(
                BackgroundTask(
                    id=task_id,
                    status="pending",
                    **task.model_dump(),
                )
            )
            await session.commit()
        return task_id

    async def delete(self, *, task_id: UUID) -> None:
        """Remove a task row the queue never accepted a job for.

        A row past ``pending`` stays: its chunks and its progress rows point at
        it with ``ondelete="CASCADE"``.
        """
        async with self._session_factory() as session:
            await session.execute(
                delete(BackgroundTask).where(
                    BackgroundTask.id == task_id,
                    BackgroundTask.status == "pending",
                )
            )
            await session.commit()

    async def get(self, *, task_id: UUID) -> BackgroundTask | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BackgroundTask).where(BackgroundTask.id == task_id)
            )
            return result.scalar_one_or_none()

    async def list_active_for_conversation(
        self,
        *,
        conversation_id: UUID,
    ) -> list[BackgroundTask]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BackgroundTask)
                .where(BackgroundTask.conversation_id == conversation_id)
                .where(BackgroundTask.status.in_(ACTIVE_TASK_STATES))
            )
            return list(result.scalars().all())

    async def reported_outcomes(
        self,
        *,
        task_ids: Sequence[UUID],
    ) -> dict[UUID, TaskOutcome]:
        """Each named task's outcome, for the tasks that already report one."""
        if not task_ids:
            return {}
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(BackgroundTask).where(
                    BackgroundTask.id.in_(list(task_ids)),
                    BackgroundTask.status.in_(REPORTED_TASK_STATES),
                ),
            )
            outcomes = [TaskOutcome.model_validate(row) for row in rows]
        return {outcome.id: outcome for outcome in outcomes}

    async def mark_running(self, *, task_id: UUID) -> None:
        await self._set_values(
            task_id,
            status="running",
            started_at=datetime.now(UTC),
        )

    async def mark_result_ready(self, *, task_id: UUID, result: dict[str, Any]) -> None:
        await self._set_values(
            task_id,
            status="result_ready",
            result=result,
        )

    async def mark_resuming(self, *, task_id: UUID) -> None:
        await self._set_values(task_id, status="resuming")

    async def mark_complete(self, *, task_id: UUID) -> None:
        await self._set_values(
            task_id,
            status="complete",
            completed_at=datetime.now(UTC),
        )
        await self._notify_terminal(task_id=task_id)

    async def mark_failed(self, *, task_id: UUID, error: str) -> None:
        await self._set_values(
            task_id,
            status="failed",
            error=error,
            completed_at=datetime.now(UTC),
        )
        await self._notify_terminal(task_id=task_id)

    async def _set_values(self, task_id: UUID, **values: Any) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(**values)
            )
            await session.commit()

    async def _notify_terminal(self, *, task_id: UUID) -> None:
        """Wake a stream listening on ``chat_events:<conversation_id>``.

        A reader of the stream re-checks the task's status after every
        notification, so a terminal task ends the wait at once.
        """
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(BackgroundTask.conversation_id).where(
                        BackgroundTask.id == task_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return
            await session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {
                    "channel": f"chat_events:{row}",
                    "payload": str(task_id),
                },
            )
            await session.commit()


__all__ = [
    "ACTIVE_TASK_STATES",
    "REPORTED_TASK_STATES",
    "BackgroundTaskRepository",
    "NewBackgroundTask",
    "TaskOutcome",
]
