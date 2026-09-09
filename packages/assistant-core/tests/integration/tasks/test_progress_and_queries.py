"""What a task's progress writes, and what a thread's task listing reads."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from tests.conftest import seed_host_user

from assistant_core.persistence.models import (
    Conversation,
    ConversationEvent,
    TaskProgressRow,
)
from assistant_core.persistence.repositories.background_tasks import (
    BackgroundTaskRepository,
    NewBackgroundTask,
)
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.progress import TaskProgressEmitter
from assistant_core.tasks.queries import latest_progress_by_task, list_task_rows

SITE = "synthetic"
HOME = "pathfinder"
OTHER = "companion"


@pytest.fixture
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


@pytest.fixture
async def thread(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> tuple[UUID, UUID]:
    del db_cleaner, patch_app_db_engine, under_home
    conversation_id, user_id = uuid4(), uuid4()
    await seed_host_user(user_id)
    async with async_session_factory() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                site_id=SITE,
                application_id=HOME,
            ),
        )
        await session.commit()
    return conversation_id, user_id


async def _task(thread: tuple[UUID, UUID], tool_name: str) -> UUID:
    conversation_id, user_id = thread
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    return await repo.create(
        task=NewBackgroundTask(
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name=tool_name,
            tool_call_id=f"call_{tool_name}",
            args={},
            estimated_duration_seconds=90,
            phase_overrides={},
        ),
    )


async def _progress_rows(task_id: UUID) -> list[TaskProgressRow]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(TaskProgressRow)
            .where(TaskProgressRow.task_id == task_id)
            .order_by(TaskProgressRow.id),
        )
        return list(rows)


async def _thread_chunks(conversation_id: UUID) -> list[dict[str, object]]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id),
        )
        return [row.chunk for row in rows]


async def test_every_update_writes_its_own_row_and_the_first_reaches_the_thread(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    task_id = await _task(thread, "crunch")
    emitter = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=conversation_id,
        session_factory=async_session_factory,
    )

    await emitter.update(percent=0.1, message="starting")
    await emitter.update(percent=0.12, message="still starting")
    await emitter.aclose()

    rows = await _progress_rows(task_id)
    assert [(row.percent, row.message) for row in rows] == [
        (0.1, "starting"),
        (0.12, "still starting"),
    ]
    chunks = await _thread_chunks(conversation_id)
    assert [chunk["type"] for chunk in chunks] == [
        "data-task-progress",
        "data-task-progress",
    ]


async def test_a_batching_emitter_holds_its_rows_until_the_buffer_fills(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    task_id = await _task(thread, "crunch")
    emitter = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=conversation_id,
        session_factory=async_session_factory,
        batch_size=3,
        max_flush_interval_seconds=1000.0,
    )

    await emitter.update(percent=0.1, message="one")
    held = await _progress_rows(task_id)
    await emitter.update(percent=0.2, message="two")
    await emitter.update(percent=0.3, message="three")
    flushed = await _progress_rows(task_id)

    assert held == []
    assert [row.message for row in flushed] == ["one", "two", "three"]


async def test_closing_flushes_what_the_buffer_still_holds(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    task_id = await _task(thread, "crunch")
    emitter = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=conversation_id,
        session_factory=async_session_factory,
        batch_size=10,
        max_flush_interval_seconds=1000.0,
    )

    await emitter.update(percent=0.4, message="only one")
    await emitter.aclose()

    assert [row.message for row in await _progress_rows(task_id)] == ["only one"]


async def test_a_scoped_child_tags_its_rows_with_the_scope(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    task_id = await _task(thread, "crunch")
    parent = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=conversation_id,
        session_factory=async_session_factory,
    )

    await parent.scoped(variantId="v3").update(percent=0.5, message="halfway")

    rows = await _progress_rows(task_id)
    assert [row.data for row in rows] == [{"variantId": "v3"}]


async def test_the_listing_reports_a_thread_s_tasks_newest_first(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, user_id = thread
    first = await _task(thread, "crunch")
    second = await _task(thread, "sift")

    rows = await list_task_rows(
        conversation_id=conversation_id,
        user_id=user_id,
        statuses=None,
    )

    assert {row.id for row in rows} == {first, second}
    assert {row.tool_name for row in rows} == {"crunch", "sift"}
    assert all(row.status == "pending" for row in rows)


async def test_the_listing_filters_by_status(thread: tuple[UUID, UUID]) -> None:
    conversation_id, user_id = thread
    pending = await _task(thread, "crunch")
    done = await _task(thread, "sift")
    repo = BackgroundTaskRepository(session_factory=async_session_factory)
    await repo.mark_complete(task_id=done)

    rows = await list_task_rows(
        conversation_id=conversation_id,
        user_id=user_id,
        statuses={"pending"},
    )

    assert [row.id for row in rows] == [pending]


async def test_a_caller_of_another_application_reads_no_task(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, user_id = thread
    await _task(thread, "crunch")

    token = application_id_ctx.set(OTHER)
    try:
        rows = await list_task_rows(
            conversation_id=conversation_id,
            user_id=user_id,
            statuses=None,
        )
    finally:
        application_id_ctx.reset(token)

    assert rows == []


async def test_the_newest_progress_of_each_task_comes_back(
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    task_id = await _task(thread, "crunch")
    emitter = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=conversation_id,
        session_factory=async_session_factory,
    )
    await emitter.update(percent=0.2, message="early")
    await emitter.update(percent=0.8, message="late")

    latest = await latest_progress_by_task([task_id])

    assert latest[task_id].percent == 0.8
    assert latest[task_id].message == "late"


async def test_asking_about_no_task_reads_nothing() -> None:
    assert await latest_progress_by_task([]) == {}
