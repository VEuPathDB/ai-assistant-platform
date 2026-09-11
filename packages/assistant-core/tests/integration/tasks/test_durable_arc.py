"""A durable call, end to end: the turn parks, the worker runs, the turn answers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import procrastinate
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from tests.integration.tasks.conftest import (
    CRUNCH_CALL_ID,
    CRUNCH_SECONDS,
    HOST_DURABLE_QUEUE,
    ONE_PROMPT,
    SIFT_CALL_ID,
    TWO_PROMPT,
    CarriedJobContext,
    DurableRuntime,
    WorkerRuns,
)

from assistant_core.persistence.models import BackgroundTask, ConversationEvent
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
)
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.declaration import empty_durable_tools


def _deferred(queue: procrastinate.App) -> list[dict[str, Any]]:
    """Every job the queue holds, in the order it was deferred."""
    connector = queue.connector
    assert isinstance(connector, InMemoryConnector)
    return [connector.jobs[key] for key in sorted(connector.jobs)]


async def _run_deferred(queue: procrastinate.App, job: dict[str, Any]) -> None:
    """Run one deferred job the way the worker runs it."""
    await queue.tasks[job["task_name"]].func(**job["args"])


async def _tasks_of(conversation_id: UUID) -> list[BackgroundTask]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(BackgroundTask)
            .where(BackgroundTask.conversation_id == conversation_id)
            .order_by(BackgroundTask.created_at),
        )
        return list(rows)


async def _chunks_of(conversation_id: UUID) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id),
        )
        return [row.chunk for row in rows]


async def test_a_durable_call_writes_its_row_and_defers_its_job(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
) -> None:
    await durable_runtime.run(ONE_PROMPT)

    tasks = await _tasks_of(durable_runtime.conversation_id)
    assert [task.tool_name for task in tasks] == ["crunch"]
    assert tasks[0].status == "pending"
    assert tasks[0].tool_call_id == CRUNCH_CALL_ID
    assert tasks[0].args == {"args": [], "kwargs": {"n": 2}}

    jobs = _deferred(task_queue)
    assert [job["task_name"] for job in jobs] == ["durable:crunch"]
    assert jobs[0]["queue_name"] == HOST_DURABLE_QUEUE
    assert jobs[0]["lock"] == str(durable_runtime.conversation_id)
    assert jobs[0]["args"]["task_id"] == str(tasks[0].id)
    assert jobs[0]["args"]["thread_id"] == str(
        durable_runtime.conversation_id,
    )


async def test_the_parked_turn_announces_the_task_and_suspends(
    durable_runtime: DurableRuntime,
) -> None:
    await durable_runtime.run(ONE_PROMPT)

    tasks = await _tasks_of(durable_runtime.conversation_id)
    started = [
        chunk
        for chunk in durable_runtime.chunks
        if chunk["type"] == "data-background-task-started"
    ]
    assert started == [
        {
            "type": "data-background-task-started",
            "data": {
                "taskId": str(tasks[0].id),
                "toolName": "crunch",
                "estimatedDurationSeconds": CRUNCH_SECONDS,
            },
        },
    ]


async def test_the_checkpoint_carries_the_call_the_turn_parked(
    durable_runtime: DurableRuntime,
) -> None:
    await durable_runtime.run(ONE_PROMPT)

    snapshot = await durable_runtime.graph.aget_state(
        {"configurable": {"thread_id": str(durable_runtime.conversation_id)}},
    )
    parked = snapshot.values["pending_durable_call"]

    assert [call.tool_call_id for call in parked.durable_calls] == [CRUNCH_CALL_ID]
    assert [call.durable_tool_name for call in parked.durable_calls] == ["crunch"]


async def test_the_worker_runs_the_body_and_the_turn_answers_with_its_result(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
    worker_runs: WorkerRuns,
) -> None:
    await durable_runtime.run(ONE_PROMPT)
    durable_runtime.chunks.clear()

    await _run_deferred(task_queue, _deferred(task_queue)[0])

    tasks = await _tasks_of(durable_runtime.conversation_id)
    assert [call["tool"] for call in worker_runs.calls] == ["crunch"]
    assert worker_runs.calls[0]["kwargs"] == {"n": 2}
    assert worker_runs.calls[0]["task_id"] == tasks[0].id
    assert tasks[0].status == "complete"
    assert tasks[0].result == {"tool": "crunch", "counted": 2}
    texts = [
        chunk["delta"]
        for chunk in durable_runtime.chunks
        if chunk["type"] == "text-delta"
    ]
    assert "".join(texts) == (
        "Results: [{'status': 'success', 'result': {'tool': 'crunch', 'counted': 2}}]."
    )


async def test_the_thread_records_the_task_as_completed(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
) -> None:
    await durable_runtime.run(ONE_PROMPT)

    await _run_deferred(task_queue, _deferred(task_queue)[0])

    completed = [
        chunk
        for chunk in await _chunks_of(durable_runtime.conversation_id)
        if chunk["type"] == "data-task-completed"
    ]
    tasks = await _tasks_of(durable_runtime.conversation_id)
    assert completed == [
        {
            "type": "data-task-completed",
            "data": {"taskId": str(tasks[0].id), "status": "success"},
        },
    ]


async def test_a_body_that_raises_fails_its_row_and_says_so_on_the_thread(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
    worker_runs: WorkerRuns,
) -> None:
    worker_runs.fail_with = "the site did not answer"
    await durable_runtime.run(ONE_PROMPT)

    await _run_deferred(task_queue, _deferred(task_queue)[0])

    tasks = await _tasks_of(durable_runtime.conversation_id)
    assert tasks[0].status == "failed"
    assert tasks[0].error == "the site did not answer"
    completed = [
        chunk
        for chunk in await _chunks_of(durable_runtime.conversation_id)
        if chunk["type"] == "data-task-completed"
    ]
    assert completed[0]["data"]["status"] == "failed"
    assert completed[0]["data"]["error"] == "the site did not answer"


async def test_a_job_naming_a_tool_this_process_has_no_body_for_fails_the_row(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
) -> None:
    await durable_runtime.run(ONE_PROMPT)
    job = _deferred(task_queue)[0]
    task_id = job["args"]["task_id"]

    # A worker process that registered no body for this tool.
    with empty_durable_tools():
        await _run_deferred(task_queue, job)

    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    row = await repo.get(task_id=UUID(task_id))
    assert row is not None
    assert row.status == "failed"
    assert row.error == "unknown durable tool: crunch"


async def test_the_host_state_the_call_captured_is_restored_around_the_body(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
    worker_runs: WorkerRuns,
    carried_job_context: CarriedJobContext,
) -> None:
    del carried_job_context
    await durable_runtime.run(ONE_PROMPT)
    job = _deferred(task_queue)[0]
    assert job["args"]["job_context"] == {"token": "carried-token"}

    await _run_deferred(task_queue, job)

    assert worker_runs.restored == [{"token": "carried-token"}]


async def test_two_calls_of_one_step_wait_for_the_last_task_to_report(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
    worker_runs: WorkerRuns,
) -> None:
    await durable_runtime.run(TWO_PROMPT)
    # The step defers its two calls together, so the queue order is not fixed.
    jobs = {job["task_name"]: job for job in _deferred(task_queue)}
    assert sorted(jobs) == ["durable:crunch", "durable:sift"]
    durable_runtime.chunks.clear()

    await _run_deferred(task_queue, jobs["durable:crunch"])
    after_first = list(durable_runtime.chunks)
    await _run_deferred(task_queue, jobs["durable:sift"])

    assert after_first == []
    assert [call["tool"] for call in worker_runs.calls] == ["crunch", "sift"]
    texts = [
        chunk["delta"]
        for chunk in durable_runtime.chunks
        if chunk["type"] == "text-delta"
    ]
    joined = "".join(texts)
    assert "'tool': 'crunch'" in joined
    assert "'tool': 'sift'" in joined
    tasks = await _tasks_of(durable_runtime.conversation_id)
    assert sorted(task.status for task in tasks) == ["complete", "complete"]


async def test_the_parked_step_carries_one_call_per_deferred_tool(
    durable_runtime: DurableRuntime,
) -> None:
    await durable_runtime.run(TWO_PROMPT)

    snapshot = await durable_runtime.graph.aget_state(
        {"configurable": {"thread_id": str(durable_runtime.conversation_id)}},
    )
    parked = snapshot.values["pending_durable_call"]

    assert sorted(call.tool_call_id for call in parked.durable_calls) == sorted(
        [CRUNCH_CALL_ID, SIFT_CALL_ID],
    )
    assert sorted(call.durable_tool_name for call in parked.durable_calls) == [
        "crunch",
        "sift",
    ]
    assert len({call.task_id for call in parked.durable_calls}) == 2
