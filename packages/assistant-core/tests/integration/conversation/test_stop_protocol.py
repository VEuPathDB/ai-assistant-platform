"""Stopping a turn: the request row, the wait, and who may ask."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from tests.conftest import seed_host_user

from assistant_core.conversation.cancellation import (
    cancel_active_turn,
    cancel_in_flight_turn,
    stop_turn_before_delete,
    stop_turns_and_wait,
    turn_is_cancelled,
)
from assistant_core.errors import ConversationNotFoundError, TurnStillRunningError
from assistant_core.persistence.models import Conversation, ConversationEvent
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.names import CHAT_TURN_QUEUE, CHAT_TURN_TASK

HOME = "pathfinder"
OTHER = "companion"
SITE = "plasmodb"
WAIT_SECONDS = 0.4


@pytest.fixture(autouse=True)
def queue() -> Iterator[procrastinate.App]:
    """A job queue whose jobs stay in memory, as a host would install one."""
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app)
    yield app
    reset_task_app()


async def _held_chat_turn(
    app: procrastinate.App,
    *,
    conversation_id: UUID,
    turn_id: UUID,
) -> int:
    """A chat-turn job whose worker stopped answering."""
    job = app.configure_task(
        name=CHAT_TURN_TASK,
        queue=CHAT_TURN_QUEUE,
        lock=str(conversation_id),
    )
    job_id = await job.defer_async(
        payload={
            "turn_id": str(turn_id),
            "body": {"conversationId": str(conversation_id)},
        },
    )
    connector = app.connector
    assert isinstance(connector, InMemoryConnector)
    connector.jobs[job_id]["status"] = "doing"
    connector.jobs[job_id]["worker_id"] = 7
    return job_id


def _job_status(app: procrastinate.App, job_id: int) -> str:
    connector = app.connector
    assert isinstance(connector, InMemoryConnector)
    return str(connector.jobs[job_id]["status"])


@pytest.fixture
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


async def _thread(user_id: UUID, application_id: str = HOME) -> UUID:
    conversation_id = uuid4()
    async with async_session_factory() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                site_id=SITE,
                name="kinases",
                application_id=application_id,
            ),
        )
        await session.commit()
    return conversation_id


async def _append(conversation_id: UUID, turn_id: UUID, chunk_type: str) -> None:
    async with async_session_factory() as session:
        session.add(
            ConversationEvent(
                conversation_id=conversation_id,
                turn_id=turn_id,
                chunk={"type": chunk_type},
            ),
        )
        await session.commit()


async def test_a_stop_writes_a_request_the_running_worker_reads(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")

    assert await cancel_in_flight_turn(conversation_id) is True
    assert await turn_is_cancelled(conversation_id=conversation_id, turn_id=turn_id)


async def test_a_thread_whose_turn_already_closed_has_nothing_to_stop(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")
    await _append(conversation_id, turn_id, "done")

    assert await cancel_in_flight_turn(conversation_id) is False
    assert not await turn_is_cancelled(
        conversation_id=conversation_id,
        turn_id=turn_id,
    )


async def test_the_newest_open_turn_is_the_one_that_is_stopped(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id = await _thread(owner)
    first, second = uuid4(), uuid4()
    await _append(conversation_id, first, "text-delta")
    await _append(conversation_id, first, "done")
    await _append(conversation_id, second, "text-delta")

    await cancel_in_flight_turn(conversation_id)

    assert await turn_is_cancelled(conversation_id=conversation_id, turn_id=second)
    assert not await turn_is_cancelled(conversation_id=conversation_id, turn_id=first)


async def test_a_caller_of_another_application_cannot_stop_the_thread(
    owner: UUID,
    under_home: None,
    queue: procrastinate.App,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner, OTHER), uuid4()
    await _append(conversation_id, turn_id, "text-delta")
    job_id = await _held_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    async with async_session_factory() as session:
        with pytest.raises(ConversationNotFoundError):
            await cancel_active_turn(
                session,
                conversation_id=conversation_id,
                user_id=owner,
            )

    assert _job_status(queue, job_id) == "doing"
    assert not await turn_is_cancelled(
        conversation_id=conversation_id,
        turn_id=turn_id,
    )


async def test_the_owner_stops_the_turn_and_a_dead_worker_s_job_is_released(
    owner: UUID,
    under_home: None,
    queue: procrastinate.App,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")
    job_id = await _held_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    async with async_session_factory() as session:
        await cancel_active_turn(
            session,
            conversation_id=conversation_id,
            user_id=owner,
        )

    assert _job_status(queue, job_id) == "failed"
    assert await turn_is_cancelled(conversation_id=conversation_id, turn_id=turn_id)


async def test_a_worker_that_never_closes_its_turn_is_reported_as_pending(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")

    pending = await stop_turns_and_wait(
        [conversation_id],
        timeout_seconds=WAIT_SECONDS,
    )

    assert pending == [conversation_id]
    assert await turn_is_cancelled(conversation_id=conversation_id, turn_id=turn_id)


async def test_a_delete_refuses_while_the_worker_still_holds_the_turn(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")

    with pytest.raises(TurnStillRunningError) as caught:
        await stop_turn_before_delete(
            conversation_id,
            timeout_seconds=WAIT_SECONDS,
        )

    assert caught.value.conversation_id == conversation_id


async def test_the_wait_ends_as_soon_as_the_worker_closes_its_turn(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")

    async def _close_it() -> None:
        await asyncio.sleep(WAIT_SECONDS / 4)
        await _append(conversation_id, turn_id, "done")

    closing = asyncio.create_task(_close_it())
    pending = await stop_turns_and_wait(
        [conversation_id],
        timeout_seconds=WAIT_SECONDS * 5,
    )
    await closing

    assert pending == []


async def test_stopping_no_threads_touches_nothing(
    owner: UUID,
    under_home: None,
    queue: procrastinate.App,
) -> None:
    del owner, under_home
    connector = queue.connector
    assert isinstance(connector, InMemoryConnector)

    assert await stop_turns_and_wait([]) == []
    assert connector.jobs == {}


async def test_a_stop_on_a_dead_worker_s_thread_closes_the_stream_it_left_open(
    owner: UUID,
    under_home: None,
    queue: procrastinate.App,
) -> None:
    """The worker never reads the row, so the turn ends from outside."""
    del under_home
    conversation_id, turn_id = await _thread(owner), uuid4()
    await _append(conversation_id, turn_id, "text-delta")
    job_id = await _held_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    pending = await stop_turns_and_wait(
        [conversation_id],
        timeout_seconds=WAIT_SECONDS,
    )

    assert pending == []
    assert _job_status(queue, job_id) == "failed"
