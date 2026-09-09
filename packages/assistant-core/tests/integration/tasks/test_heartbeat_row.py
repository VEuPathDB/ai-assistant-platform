"""The heartbeat row advances while a job holds the worker's event loop."""

from __future__ import annotations

import time

import procrastinate
import psycopg
import pytest
from procrastinate.worker import Worker

from assistant_core.conversation.checkpointer import to_psycopg_url
from assistant_core.platform.config import get_runtime_settings
from assistant_core.tasks.heartbeat import HeartbeatThread, postgres_beat_writer

_BLOCK_SECONDS = 2.0
_INTERVAL_SECONDS = 0.25

_AGE_QUERY = (
    "SELECT extract(epoch FROM now() - max(last_heartbeat)) FROM procrastinate_workers"
)


def block_the_event_loop(seconds: float) -> None:
    """What a job with a synchronous call does to the worker's loop."""
    time.sleep(seconds)


def _heartbeat_age(psycopg_url: str) -> float:
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(_AGE_QUERY)
        row = cursor.fetchone()
    assert row is not None
    return float(row[0])


async def _run_probe_worker(*, with_heartbeat_thread: bool) -> float:
    """Run one job that blocks the loop; report the heartbeat age it saw."""
    settings = get_runtime_settings()
    psycopg_url = to_psycopg_url(settings.database_url)
    app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=psycopg_url),
    )
    ages: list[float] = []

    @app.task(queue="heartbeat_probe", name="heartbeat_probe")
    async def probe() -> None:
        block_the_event_loop(_BLOCK_SECONDS)
        ages.append(_heartbeat_age(psycopg_url))

    async with app.open_async():
        await probe.defer_async()
        worker = Worker(
            app=app,
            queues=["heartbeat_probe"],
            concurrency=1,
            wait=False,
            listen_notify=False,
            install_signal_handlers=False,
            update_heartbeat_interval=_INTERVAL_SECONDS,
        )
        heartbeat = HeartbeatThread(
            worker_id=lambda: worker.worker_id,
            write=postgres_beat_writer(settings.database_url),
            interval_seconds=_INTERVAL_SECONDS,
        )
        if with_heartbeat_thread:
            heartbeat.start()
        try:
            await worker.run()
        finally:
            if with_heartbeat_thread:
                heartbeat.stop()

    assert len(ages) == 1
    return ages[0]


@pytest.mark.usefixtures("procrastinate_schema")
async def test_the_heartbeat_row_stays_fresh_through_a_blocking_job() -> None:
    """The thread keeps the row inside its own interval, not the job's length."""
    age = await _run_probe_worker(with_heartbeat_thread=True)

    assert age < _INTERVAL_SECONDS * 3


@pytest.mark.usefixtures("procrastinate_schema")
async def test_without_the_thread_the_row_ages_with_the_job() -> None:
    """The measurement the thread answers: the row is as old as the block."""
    age = await _run_probe_worker(with_heartbeat_thread=False)

    assert age >= _BLOCK_SECONDS
