from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from tests.conftest import seed_host_user

from assistant_core.conversation.cancellation import (
    stop_turns_and_wait,
    turn_is_cancelled,
)
from assistant_core.persistence.models import Conversation, ConversationEvent
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.names import CHAT_TURN_QUEUE, CHAT_TURN_TASK

HOME = "pathfinder"
WAIT_SECONDS = 2.0


@pytest.fixture(autouse=True)
def queue() -> Iterator[procrastinate.App]:
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app)
    yield app
    reset_task_app()


@pytest.fixture(autouse=True)
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


@pytest.fixture
async def owner(db_cleaner: None, patch_app_db_engine: None) -> UUID:
    del db_cleaner, patch_app_db_engine
    user_id = uuid4()
    await seed_host_user(user_id)
    return user_id


async def _thread(user_id: UUID) -> UUID:
    conversation_id = uuid4()
    async with async_session_factory() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                site_id="plasmodb",
                name="kinases",
                application_id=HOME,
            ),
        )
        await session.commit()
    return conversation_id


async def _asked(conversation_id: UUID, turn_id: UUID) -> None:
    async with async_session_factory() as session:
        session.add(
            ConversationEvent(
                conversation_id=conversation_id,
                turn_id=turn_id,
                chunk={"type": "data-user-message"},
            ),
        )
        await session.commit()


async def _queued_turn(
    app: procrastinate.App, conversation_id: UUID, turn_id: UUID
) -> int:
    job = app.configure_task(
        name=CHAT_TURN_TASK,
        queue=CHAT_TURN_QUEUE,
        lock=str(conversation_id),
    )
    return await job.defer_async(
        payload={
            "turn_id": str(turn_id),
            "body": {"conversationId": str(conversation_id)},
        },
    )


def _status(app: procrastinate.App, job_id: int) -> str:
    connector = app.connector
    assert isinstance(connector, InMemoryConnector)
    return str(connector.jobs[job_id]["status"])


async def _chunks(conversation_id: UUID, turn_id: UUID) -> list[dict[str, object]]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent)
            .where(
                ConversationEvent.conversation_id == conversation_id,
                ConversationEvent.turn_id == turn_id,
            )
            .order_by(ConversationEvent.id),
        )
        return [dict(row.chunk) for row in rows]


async def test_a_turn_still_in_the_queue_is_cancelled_and_closed_as_stopped(
    owner: UUID, queue: procrastinate.App
) -> None:
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _asked(conversation_id, turn_id)
    job_id = await _queued_turn(queue, conversation_id, turn_id)

    started = time.monotonic()
    pending = await stop_turns_and_wait([conversation_id], timeout_seconds=WAIT_SECONDS)

    assert pending == []
    assert time.monotonic() - started < WAIT_SECONDS / 2
    assert _status(queue, job_id) == "cancelled"
    assert [chunk["type"] for chunk in await _chunks(conversation_id, turn_id)] == [
        "data-user-message",
        "data-turn-stopped",
        "finish",
        "done",
    ]
    assert (await _chunks(conversation_id, turn_id))[2]["finishReason"] == "other"
    assert await turn_is_cancelled(conversation_id=conversation_id, turn_id=turn_id)


async def test_a_turn_a_worker_already_runs_is_left_to_its_worker(
    owner: UUID, queue: procrastinate.App
) -> None:
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _asked(conversation_id, turn_id)
    job_id = await _queued_turn(queue, conversation_id, turn_id)
    connector = queue.connector
    assert isinstance(connector, InMemoryConnector)
    worker = await connector.register_worker_one()
    connector.jobs[job_id]["status"] = "doing"
    connector.jobs[job_id]["worker_id"] = worker["worker_id"]

    pending = await stop_turns_and_wait([conversation_id], timeout_seconds=0.3)

    assert pending == [conversation_id]
    assert _status(queue, job_id) == "doing"
    assert [chunk["type"] for chunk in await _chunks(conversation_id, turn_id)] == [
        "data-user-message",
    ]


async def test_another_thread_s_queued_turn_is_left_alone(
    owner: UUID, queue: procrastinate.App
) -> None:
    stopped, other = await _thread(owner), await _thread(owner)
    stopped_turn, other_turn = uuid4(), uuid4()
    await _asked(stopped, stopped_turn)
    await _asked(other, other_turn)
    await _queued_turn(queue, stopped, stopped_turn)
    other_job = await _queued_turn(queue, other, other_turn)

    assert await stop_turns_and_wait([stopped], timeout_seconds=WAIT_SECONDS) == []

    assert _status(queue, other_job) == "todo"
    assert [chunk["type"] for chunk in await _chunks(other, other_turn)] == [
        "data-user-message",
    ]


async def test_a_queued_job_of_an_older_turn_is_not_the_open_turn_s(
    owner: UUID, queue: procrastinate.App
) -> None:
    conversation_id, older, newest = await _thread(owner), uuid4(), uuid4()
    older_job = await _queued_turn(queue, conversation_id, older)
    await _asked(conversation_id, newest)

    pending = await stop_turns_and_wait([conversation_id], timeout_seconds=0.3)

    assert pending == [conversation_id]
    assert _status(queue, older_job) == "todo"
