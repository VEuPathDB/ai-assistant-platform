"""A durable task's incremental progress, on two channels.

The worker persists every update to ``task_progress`` and fires a
``pg_notify`` on ``task_progress:<conversation_id>``, and it appends a
coalesced subset to the thread's own log so a reader of the main stream sees
the task advance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text

from assistant_core.conversation.event_writer import append_chunk
from assistant_core.graph.stream_events import task_progress_event
from assistant_core.persistence.models import TaskProgressRow
from assistant_core.platform.db import DBSessionFactory

# The log is the coarse channel: it answers "where is this task now" for a
# reader that reconnects. An update reaches it when the task advances five
# percentage points, or when the last one it holds is this old.
_LOG_ADVANCE_POINTS = 5
_LOG_MAX_SILENCE_SECONDS = 10.0


@dataclass(frozen=True)
class _PendingProgress:
    percent: float
    message: str
    data: dict[str, Any] | None


def _points(percent: float) -> int:
    return round(percent * 100)


def _lane_of(scope: dict[str, Any]) -> str | None:
    """The thread-log lane a scope names, or None when it names nothing."""
    return ":".join(str(value) for _, value in sorted(scope.items())) or None


@dataclass
class _ThreadLog:
    """Which of a task's updates reach the conversation log.

    One instance per lane. A lane is a part of its own on the thread, so it
    carries its own id and spends a budget of its own.
    """

    conversation_id: UUID
    task_id: UUID
    lane: str | None = None
    written_points: int | None = None
    written_at: float = 0.0
    unwritten: _PendingProgress | None = None

    def _is_due(self, row: _PendingProgress, now: float) -> bool:
        if self.written_points is None:
            return True
        if _points(row.percent) - self.written_points >= _LOG_ADVANCE_POINTS:
            return True
        return now - self.written_at >= _LOG_MAX_SILENCE_SECONDS

    async def offer(self, row: _PendingProgress) -> None:
        self.unwritten = row
        if self._is_due(row, time.monotonic()):
            await self._append(row)

    async def write_last(self) -> None:
        """Append the newest update the log does not hold yet."""
        if self.unwritten is not None:
            await self._append(self.unwritten)

    async def _append(self, row: _PendingProgress) -> None:
        await append_chunk(
            conversation_id=self.conversation_id,
            chunk=task_progress_event(
                task_id=self.task_id,
                percent=row.percent,
                message=row.message,
                tool_specific=row.data,
                lane=self.lane,
            ).model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        self.written_points = _points(row.percent)
        self.written_at = time.monotonic()
        if self.unwritten is row:
            self.unwritten = None


@dataclass
class TaskProgressEmitter:
    """Records a durable task's incremental progress.

    By default (``batch_size=1``) each :meth:`update` commits at once and
    fires one ``pg_notify``. A caller that emits many rows rapidly sets
    ``batch_size`` above one: rows buffer in memory and flush when the buffer
    fills, when :attr:`max_flush_interval_seconds` elapses, or on
    :meth:`flush` or :meth:`aclose`.

    :meth:`scoped` derives a child emitter that tags every payload with a
    fixed scope, so each branch of a fan-out reports in a lane of its own.
    """

    task_id: UUID
    conversation_id: UUID
    session_factory: DBSessionFactory
    batch_size: int = 1
    max_flush_interval_seconds: float = 1.0
    _scope_data: dict[str, Any] = field(default_factory=dict)
    _buffer: list[_PendingProgress] = field(default_factory=list)
    _last_flush_monotonic: float = field(default=0.0)
    _thread_log: _ThreadLog = field(init=False)

    def __post_init__(self) -> None:
        self._thread_log = _ThreadLog(
            conversation_id=self.conversation_id,
            task_id=self.task_id,
        )

    def scoped(self, **scope: Any) -> TaskProgressEmitter:
        """Return a child emitter that tags every update with ``scope``.

        The scope's values name the child's lane on the thread, so each child
        of a fan-out reconciles into a part of its own.
        """
        child = TaskProgressEmitter(
            task_id=self.task_id,
            conversation_id=self.conversation_id,
            session_factory=self.session_factory,
            batch_size=self.batch_size,
            max_flush_interval_seconds=self.max_flush_interval_seconds,
        )
        child._scope_data = {**self._scope_data, **scope}
        child._thread_log = _ThreadLog(
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            lane=_lane_of(child._scope_data),
        )
        return child

    async def update(
        self,
        *,
        percent: float,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        merged: dict[str, Any] | None
        if self._scope_data or data is not None:
            merged = {**self._scope_data, **(data or {})}
        else:
            merged = None
        row = _PendingProgress(percent=percent, message=message, data=merged)
        self._buffer.append(row)
        now = time.monotonic()
        if self._last_flush_monotonic == 0.0:
            self._last_flush_monotonic = now
        should_flush = (
            len(self._buffer) >= self.batch_size
            or (now - self._last_flush_monotonic) >= self.max_flush_interval_seconds
        )
        if should_flush:
            await self.flush()
        await self._thread_log.offer(row)

    async def flush(self) -> None:
        """Commit every buffered row and fire one notification."""
        if not self._buffer:
            return
        pending = list(self._buffer)
        self._buffer.clear()
        async with self.session_factory() as session:
            session.add_all(
                TaskProgressRow(
                    task_id=self.task_id,
                    percent=row.percent,
                    message=row.message,
                    data=row.data,
                )
                for row in pending
            )
            await session.flush()
            await session.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {
                    "channel": f"task_progress:{self.conversation_id}",
                    "payload": str(self.task_id),
                },
            )
            await session.commit()
        self._last_flush_monotonic = time.monotonic()

    async def aclose(self) -> None:
        await self.flush()
        await self._thread_log.write_last()


__all__ = ["TaskProgressEmitter"]
