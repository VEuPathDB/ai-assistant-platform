"""Every line the runner writes about a durable task names the task, its thread and its owner."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stdout
from typing import Any
from uuid import UUID, uuid4

import procrastinate
from procrastinate.testing import InMemoryConnector
from tests.integration.tasks.conftest import (
    DURABLE_SITE_ID,
    ONE_PROMPT,
    DurableRuntime,
    WorkerRuns,
)

from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.logging import setup_logging
from assistant_core.tasks.completion_turn import (
    CompletionTurn,
    install_completion_turn,
)
from assistant_core.tasks.declaration import declare_durable_tool, register_durable_impl
from assistant_core.tasks.runner import run_durable_task, settle_unfinished_task

_TASK_KEYS = ("task_id", "conversation_id", "tool_name", "user_id")
_PROBE = "probe"


@contextmanager
def _rendered() -> Iterator[list[dict[str, Any]]]:
    root = logging.getLogger()
    kept, level = list(root.handlers), root.level
    sink = io.StringIO()
    with redirect_stdout(sink):
        setup_logging()
    lines: list[dict[str, Any]] = []
    try:
        yield lines
    finally:
        root.handlers = kept
        root.setLevel(level)
        lines.extend(json.loads(text) for text in sink.getvalue().splitlines())


def _one(lines: list[dict[str, Any]], event: str) -> dict[str, Any]:
    (found,) = [line for line in lines if line["event"] == event]
    return found


async def _parked_job(
    runtime: DurableRuntime, queue: procrastinate.App
) -> dict[str, Any]:
    await runtime.run(ONE_PROMPT)
    connector = queue.connector
    assert isinstance(connector, InMemoryConnector)
    (job,) = connector.jobs.values()
    return job


async def test_a_body_that_raises_is_logged_under_its_task(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
    worker_runs: WorkerRuns,
) -> None:
    job = await _parked_job(durable_runtime, task_queue)
    worker_runs.fail_with = "the site did not answer"

    with _rendered() as lines:
        await task_queue.tasks[job["task_name"]].func(**job["args"])
        logging.getLogger("procrastinate.worker").warning("after the task")

    failed = _one(lines, "durable tool failed")
    assert {key: failed[key] for key in _TASK_KEYS} == {
        "task_id": job["args"]["task_id"],
        "conversation_id": str(durable_runtime.conversation_id),
        "tool_name": "crunch",
        "user_id": str(durable_runtime.user_id),
    }
    assert "the site did not answer" in failed["exception"]
    assert set(_TASK_KEYS) & set(_one(lines, "after the task")) == set()


async def test_the_completion_turn_is_logged_under_the_task_that_opened_it(
    durable_runtime: DurableRuntime,
    task_queue: procrastinate.App,
) -> None:
    job = await _parked_job(durable_runtime, task_queue)

    async def answer(turn: CompletionTurn) -> None:
        logging.getLogger("pydantic_ai").warning("completion line")
        await durable_runtime.answer(turn)

    install_completion_turn(answer)

    with _rendered() as lines:
        await task_queue.tasks[job["task_name"]].func(**job["args"])

    line = _one(lines, "completion line")
    assert {key: line[key] for key in _TASK_KEYS} == {
        "task_id": job["args"]["task_id"],
        "conversation_id": str(durable_runtime.conversation_id),
        "tool_name": "crunch",
        "user_id": str(durable_runtime.user_id),
    }


async def _probe_body(**kwargs: Any) -> dict[str, Any]:
    del kwargs
    logging.getLogger("httpx").warning("body line")
    return {}


def _declared_probe() -> None:
    register_durable_impl(
        declare_durable_tool(tool_name=_PROBE, estimated_duration_seconds=10),
        _probe_body,
    )


async def _row(runtime: DurableRuntime) -> UUID:
    return await BackgroundTaskRepository(session_factory=async_session_factory).create(
        task=NewBackgroundTask(
            conversation_id=runtime.conversation_id,
            user_id=runtime.user_id,
            tool_name=_PROBE,
            tool_call_id="call_probe",
            args={"args": [], "kwargs": {}},
            estimated_duration_seconds=10,
            phase_overrides={},
        ),
    )


async def test_a_body_line_names_the_task_its_owner_and_its_site(
    durable_runtime: DurableRuntime,
) -> None:
    _declared_probe()
    task_id = await _row(durable_runtime)

    with _rendered() as lines:
        await run_durable_task(
            tool_name=_PROBE,
            task_id=str(task_id),
            thread_id=str(durable_runtime.conversation_id),
            args={"args": [], "kwargs": {}},
        )

    line = _one(lines, "body line")
    assert {key: line[key] for key in (*_TASK_KEYS, "site_id")} == {
        "task_id": str(task_id),
        "conversation_id": str(durable_runtime.conversation_id),
        "tool_name": _PROBE,
        "user_id": str(durable_runtime.user_id),
        "site_id": DURABLE_SITE_ID,
    }
    assert "site_id" not in _one(lines, "no parked durable call to answer")


async def test_a_task_with_no_row_still_runs_and_names_no_owner(
    durable_runtime: DurableRuntime,
) -> None:
    _declared_probe()
    task_id = uuid4()

    with _rendered() as lines:
        await run_durable_task(
            tool_name=_PROBE,
            task_id=str(task_id),
            thread_id=str(durable_runtime.conversation_id),
            args={"args": [], "kwargs": {}},
        )

    assert _one(lines, "body line")["task_id"] == str(task_id)
    settled = _one(lines, "no parked durable call to answer")
    assert {
        key: settled[key] for key in ("task_id", "conversation_id", "tool_name")
    } == {
        "task_id": str(task_id),
        "conversation_id": str(durable_runtime.conversation_id),
        "tool_name": _PROBE,
    }
    assert "user_id" not in settled


async def test_a_task_the_sweep_settles_is_logged_under_its_task(
    durable_runtime: DurableRuntime,
) -> None:
    _declared_probe()
    task_id = await _row(durable_runtime)
    await BackgroundTaskRepository(session_factory=async_session_factory).mark_running(
        task_id=task_id
    )

    with _rendered() as lines:
        await settle_unfinished_task(
            task_id=task_id,
            conversation_id=durable_runtime.conversation_id,
            error="the worker stopped",
            job_context={},
        )
        logging.getLogger("procrastinate.worker").warning("after the sweep")

    line = _one(lines, "no parked durable call to answer")
    assert {key: line[key] for key in _TASK_KEYS} == {
        "task_id": str(task_id),
        "conversation_id": str(durable_runtime.conversation_id),
        "tool_name": _PROBE,
        "user_id": str(durable_runtime.user_id),
    }
    assert set(_TASK_KEYS) & set(_one(lines, "after the sweep")) == set()
