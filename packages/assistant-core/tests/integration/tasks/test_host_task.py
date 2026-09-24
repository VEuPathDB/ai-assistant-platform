"""A task the host starts: its own lock, nothing on the thread, no turn."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import asyncpg
import procrastinate
import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from tests.integration.tasks.conftest import (
    HOST_LOCK,
    HOST_SECONDS,
    HOST_TOOL,
    HOST_UPLOAD_ID,
    HostRuns,
    HostThread,
)

from assistant_core.conversation.checkpointer import to_psycopg_url
from assistant_core.graph.turn_state import DurableTaskResult
from assistant_core.persistence.models import (
    BackgroundTask,
    ConversationEvent,
    TaskProgressRow,
)
from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.declaration import DurableTool
from assistant_core.tasks.host_task import start_host_task
from assistant_core.tasks.runner import register_durable_jobs
from assistant_core.tasks.service import has_active_task

# A queue of this suite's own, so its rows are the only ones it removes.
HOST_QUEUE = "host_task_probe"
INSTALL_REFUSED = "The site refused the file."


class _StoredJob(BaseModel):
    """One job as ``procrastinate_jobs`` stores it."""

    model_config = ConfigDict(extra="ignore")

    task_name: str
    queue_name: str
    lock: str | None
    args: dict[str, Any]


@pytest.fixture
async def host_queue(
    procrastinate_schema: None,
    host_tool: DurableTool,
) -> AsyncIterator[procrastinate.App]:
    """A queue that keeps its jobs in the database, as a deployment does."""
    del procrastinate_schema, host_tool
    url = to_psycopg_url(get_runtime_settings().database_url)
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=url))
    install_task_app(app, durable_queue=HOST_QUEUE)
    register_durable_jobs(app)
    try:
        async with app.open_async():
            yield app
            await app.connector.execute_query_async(
                "DELETE FROM procrastinate_jobs WHERE queue_name = %(queue)s",
                queue=HOST_QUEUE,
            )
    finally:
        reset_task_app()


async def _start(tool: DurableTool, thread: HostThread) -> UUID:
    return await start_host_task(
        tool,
        conversation_id=thread.conversation_id,
        user_id=thread.user_id,
        kwargs={"upload_id": HOST_UPLOAD_ID},
        lock=HOST_LOCK,
    )


async def _stored_job(task_id: UUID) -> _StoredJob:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT task_name, queue_name, lock, args FROM procrastinate_jobs "
                    "WHERE args->>'task_id' = :task_id",
                ),
                {"task_id": str(task_id)},
            )
        ).one()
    return _StoredJob.model_validate(row._asdict())


async def _run_stored_job(queue: procrastinate.App, task_id: UUID) -> None:
    """Run the stored job the way the worker runs it."""
    job = await _stored_job(task_id)
    await queue.tasks[job.task_name].func(**job.args)


async def _row(task_id: UUID) -> BackgroundTask:
    async with async_session_factory() as session:
        row = await session.get(BackgroundTask, task_id)
    assert row is not None
    return row


async def _event_count(conversation_id: UUID) -> int:
    async with async_session_factory() as session:
        counted = await session.scalar(
            select(func.count())
            .select_from(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id),
        )
    return int(counted or 0)


async def _progress_messages(task_id: UUID) -> list[str]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(TaskProgressRow.message)
            .where(TaskProgressRow.task_id == task_id)
            .order_by(TaskProgressRow.id),
        )
        return list(rows)


async def test_a_host_task_defers_under_its_own_lock_and_writes_no_chunk(
    host_tool: DurableTool,
    host_thread: HostThread,
    host_queue: procrastinate.App,
) -> None:
    del host_queue
    task_id = await _start(host_tool, host_thread)

    row = await _row(task_id)
    job = await _stored_job(task_id)
    assert row.tool_call_id is None
    assert row.status == "pending"
    assert row.tool_name == HOST_TOOL
    assert row.estimated_duration_seconds == HOST_SECONDS
    assert row.args == {"args": [], "kwargs": {"upload_id": HOST_UPLOAD_ID}}
    assert job.task_name == f"durable:{HOST_TOOL}"
    assert job.queue_name == HOST_QUEUE
    assert job.lock == HOST_LOCK
    assert job.lock != str(host_thread.conversation_id)
    assert job.args["task_id"] == str(task_id)
    assert await _event_count(host_thread.conversation_id) == 0


async def test_a_host_task_that_succeeds_is_complete_with_no_turn_and_no_chunk(
    host_tool: DurableTool,
    host_thread: HostThread,
    host_queue: procrastinate.App,
    completion_turns: list[DurableTaskResult],
) -> None:
    task_id = await _start(host_tool, host_thread)

    await _run_stored_job(host_queue, task_id)

    row = await _row(task_id)
    assert row.status == "complete"
    assert row.result == {"upload_id": HOST_UPLOAD_ID}
    assert row.error is None
    assert completion_turns == []
    assert await _progress_messages(task_id) == ["Installing"]
    assert await _event_count(host_thread.conversation_id) == 0


async def test_a_host_task_that_fails_carries_its_error_and_no_chunk(
    host_tool: DurableTool,
    host_thread: HostThread,
    host_queue: procrastinate.App,
    host_runs: HostRuns,
    completion_turns: list[DurableTaskResult],
) -> None:
    host_runs.fail_with = INSTALL_REFUSED
    task_id = await _start(host_tool, host_thread)

    await _run_stored_job(host_queue, task_id)

    row = await _row(task_id)
    assert row.status == "failed"
    assert row.error == INSTALL_REFUSED
    assert completion_turns == []
    assert await _event_count(host_thread.conversation_id) == 0


async def test_a_host_task_is_not_an_active_task(
    host_tool: DurableTool,
    host_thread: HostThread,
    host_queue: procrastinate.App,
    host_runs: HostRuns,
) -> None:
    task_id = await _start(host_tool, host_thread)
    async with async_session_factory() as session:
        pending_is_active = await has_active_task(
            session,
            host_thread.conversation_id,
            host_thread.user_id,
        )

    await _run_stored_job(host_queue, task_id)

    assert pending_is_active is False
    assert host_runs.active == [False]
    assert host_runs.listed == [[(task_id, "running")]]


async def test_a_host_task_wakes_no_listener_of_its_thread(
    host_tool: DurableTool,
    host_thread: HostThread,
    host_queue: procrastinate.App,
    completion_turns: list[DurableTaskResult],
) -> None:
    """No channel a reader of the thread listens on hears the task."""
    del completion_turns
    channels = [
        f"{prefix}:{host_thread.conversation_id}"
        for prefix in ("chat_events", "conversation_events")
    ]
    heard: list[tuple[str, str]] = []
    dsn = make_url(get_runtime_settings().database_url).set(drivername="postgresql")
    listener = await asyncpg.connect(dsn=dsn.render_as_string(hide_password=False))
    try:
        for channel in channels:
            await listener.add_listener(
                channel,
                lambda _conn, _pid, name, payload: heard.append((name, payload)),
            )
        task_id = await _start(host_tool, host_thread)

        await _run_stored_job(host_queue, task_id)
        await listener.execute("SELECT 1")
    finally:
        await listener.close()

    assert (await _row(task_id)).status == "complete"
    assert heard == []
