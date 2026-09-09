"""The durable-task row, from the call that writes it to the state that ends it."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from tests.conftest import seed_host_user

from assistant_core.persistence.models import Conversation
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.db import async_session_factory

SITE = "synthetic"


@pytest.fixture
async def thread(db_cleaner: None, patch_app_db_engine: None) -> tuple[UUID, UUID]:
    del db_cleaner, patch_app_db_engine
    conversation_id, user_id = uuid4(), uuid4()
    await seed_host_user(user_id)
    async with async_session_factory() as session:
        session.add(
            Conversation(id=conversation_id, user_id=user_id, site_id=SITE),
        )
        await session.commit()
    return conversation_id, user_id


def _new_task(thread: tuple[UUID, UUID], tool_name: str) -> NewBackgroundTask:
    conversation_id, user_id = thread
    return NewBackgroundTask(
        conversation_id=conversation_id,
        user_id=user_id,
        tool_name=tool_name,
        tool_call_id=f"call_{tool_name}",
        args={"kwargs": {"n": 2}},
        estimated_duration_seconds=90,
        phase_overrides={"models": {"lead": "openai:gpt-5.6-luna"}},
    )


async def test_a_created_task_starts_pending_and_keeps_what_the_call_carried(
    thread: tuple[UUID, UUID],
) -> None:
    repo = BackgroundTaskRepository(session_factory=async_session_factory)

    task_id = await repo.create(task=_new_task(thread, "crunch"))

    row = await repo.get(task_id=task_id)
    assert row is not None
    assert row.status == "pending"
    assert row.tool_name == "crunch"
    assert row.tool_call_id == "call_crunch"
    assert row.args == {"kwargs": {"n": 2}}
    assert row.phase_overrides == {"models": {"lead": "openai:gpt-5.6-luna"}}
    assert row.estimated_duration_seconds == 90
    assert row.started_at is None
    assert row.completed_at is None


async def test_a_task_walks_from_running_to_complete(
    thread: tuple[UUID, UUID],
) -> None:
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    task_id = await repo.create(task=_new_task(thread, "crunch"))

    await repo.mark_running(task_id=task_id)
    running = await repo.get(task_id=task_id)
    await repo.mark_result_ready(task_id=task_id, result={"counted": 2})
    ready = await repo.get(task_id=task_id)
    await repo.mark_resuming(task_id=task_id)
    resuming = await repo.get(task_id=task_id)
    await repo.mark_complete(task_id=task_id)
    complete = await repo.get(task_id=task_id)

    assert running is not None
    assert ready is not None
    assert resuming is not None
    assert complete is not None
    assert running.status == "running"
    assert running.started_at is not None
    assert ready.status == "result_ready"
    assert ready.result == {"counted": 2}
    assert resuming.status == "resuming"
    assert complete.status == "complete"
    assert complete.completed_at is not None


async def test_a_failed_task_records_the_message_the_user_reads(
    thread: tuple[UUID, UUID],
) -> None:
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    task_id = await repo.create(task=_new_task(thread, "crunch"))

    await repo.mark_failed(task_id=task_id, error="the site did not answer")

    row = await repo.get(task_id=task_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error == "the site did not answer"
    assert row.completed_at is not None


async def test_the_active_tasks_of_a_thread_leave_out_the_finished_ones(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user_id = thread
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    pending = await repo.create(task=_new_task(thread, "crunch"))
    done = await repo.create(task=_new_task(thread, "sift"))
    await repo.mark_complete(task_id=done)

    active = await repo.list_active_for_conversation(conversation_id=conversation_id)

    assert [row.id for row in active] == [pending]


async def test_only_the_tasks_that_report_an_outcome_come_back(
    thread: tuple[UUID, UUID],
) -> None:
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    ready = await repo.create(task=_new_task(thread, "crunch"))
    running = await repo.create(task=_new_task(thread, "sift"))
    await repo.mark_result_ready(task_id=ready, result={"counted": 2})
    await repo.mark_running(task_id=running)

    reported = await repo.reported_outcomes(task_ids=[ready, running])

    assert list(reported) == [ready]
    assert reported[ready].result == {"counted": 2}
    assert reported[ready].failed is False


async def test_a_failed_outcome_reports_its_error_and_an_empty_result(
    thread: tuple[UUID, UUID],
) -> None:
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    task_id = await repo.create(task=_new_task(thread, "crunch"))
    await repo.mark_failed(task_id=task_id, error="boom")

    reported = await repo.reported_outcomes(task_ids=[task_id])

    assert reported[task_id].failed is True
    assert reported[task_id].error == "boom"
    assert reported[task_id].result == {}


async def test_asking_about_no_tasks_reads_nothing(
    thread: tuple[UUID, UUID],
) -> None:
    del thread
    repo = BackgroundTaskRepository(session_factory=async_session_factory)

    assert await repo.reported_outcomes(task_ids=[]) == {}


async def test_a_task_id_nobody_wrote_reads_as_nothing(
    thread: tuple[UUID, UUID],
) -> None:
    del thread
    repo = BackgroundTaskRepository(session_factory=async_session_factory)

    assert await repo.get(task_id=uuid4()) is None
