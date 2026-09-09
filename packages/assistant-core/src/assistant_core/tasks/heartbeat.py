"""The worker's heartbeat, written off the event loop the jobs run on.

The sweep reads this beat to decide which workers are dead, so the beat and
the dead-worker window belong to the same package.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

# A beat this many intervals late is reported.
GAP_WARNING_INTERVALS = 3

_UPDATE_HEARTBEAT = text("SELECT procrastinate_update_heartbeat_v1(:worker_id)")

type WorkerIdSource = Callable[[], int | None]
type BeatWriter = Callable[[int], Coroutine[Any, Any, None]]


def postgres_beat_writer(database_url: str) -> BeatWriter:
    """Refresh ``procrastinate_workers.last_heartbeat`` on a fresh connection.

    ``NullPool`` keeps every beat on a connection of its own, so the beat
    belongs to the loop of the thread that writes it and a broken connection
    costs one beat.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)

    async def write(worker_id: int) -> None:
        async with engine.begin() as connection:
            await connection.execute(_UPDATE_HEARTBEAT, {"worker_id": worker_id})

    return write


class HeartbeatThread:
    """Beats for the worker process from a thread with its own loop.

    Procrastinate runs its heartbeat as a task beside the jobs, so a job that
    holds the event loop stops the beat and the sweep reads a live worker as
    dead. A thread does not share that loop.
    """

    def __init__(
        self,
        *,
        worker_id: WorkerIdSource,
        write: BeatWriter,
        interval_seconds: float,
    ) -> None:
        self._worker_id = worker_id
        self._write = write
        self._interval = interval_seconds
        self._gap_warning = interval_seconds * GAP_WARNING_INTERVALS
        self._stopping = threading.Event()
        self._last_beat: float | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="worker-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=self._interval * GAP_WARNING_INTERVALS)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            while not self._stopping.is_set():
                loop.run_until_complete(self._beat())
                self._stopping.wait(self._interval)
        finally:
            loop.close()
            if not self._stopping.is_set():
                logger.error("the worker heartbeat thread stopped")

    async def _beat(self) -> None:
        worker_id = self._worker_id()
        if worker_id is None:
            return
        try:
            await self._write(worker_id)
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("the worker heartbeat was not written", error=str(exc))
            return
        self._report_gap()

    def _report_gap(self) -> None:
        landed = time.monotonic()
        previous = self._last_beat
        self._last_beat = landed
        if previous is None:
            return
        gap = landed - previous
        if gap > self._gap_warning:
            logger.warning(
                "worker heartbeat gap",
                seconds=round(gap, 1),
                interval_seconds=self._interval,
            )


__all__ = [
    "GAP_WARNING_INTERVALS",
    "BeatWriter",
    "HeartbeatThread",
    "WorkerIdSource",
    "postgres_beat_writer",
]
