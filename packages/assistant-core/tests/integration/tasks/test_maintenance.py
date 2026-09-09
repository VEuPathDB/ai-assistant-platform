"""What happens to the turn a killed worker was writing."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from structlog.testing import capture_logs
from tests.conftest import seed_host_user

from assistant_core.conversation.event_writer import append_chunk
from assistant_core.persistence.models import Conversation, ConversationEvent
from assistant_core.platform.db import async_session_factory
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.chat_turn import ChatTurnJobArgs
from assistant_core.tasks.maintenance import release_dead_turn, release_stalled_jobs
from assistant_core.tasks.names import CHAT_TURN_QUEUE, CHAT_TURN_TASK

SITE = "synthetic"


@pytest.fixture
def queue() -> Iterator[procrastinate.App]:
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app)
    yield app
    reset_task_app()


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


async def _open_turn(conversation_id: UUID, turn_id: UUID) -> None:
    """Write the start chunk a turn opens with, and nothing that closes it."""
    await append_chunk(
        conversation_id=conversation_id,
        turn_id=turn_id,
        chunk={"type": "start", "messageId": str(turn_id)},
    )


async def _defer_chat_turn(
    app: procrastinate.App,
    *,
    conversation_id: UUID,
    turn_id: UUID,
) -> int:
    """Defer a chat-turn job the way a host's dispatcher defers one."""
    return await _defer_payload(
        app,
        conversation_id=conversation_id,
        payload={
            "turn_id": str(turn_id),
            "body": {"conversationId": str(conversation_id)},
        },
    )


async def _defer_payload(
    app: procrastinate.App,
    *,
    conversation_id: UUID,
    payload: dict[str, Any],
) -> int:
    job = app.configure_task(
        name=CHAT_TURN_TASK,
        queue=CHAT_TURN_QUEUE,
        lock=str(conversation_id),
    )
    return await job.defer_async(payload=payload)


def _hold(app: procrastinate.App, job_id: int) -> None:
    """Put the job in the state a worker that then died would leave it in."""
    connector = app.connector
    assert isinstance(connector, InMemoryConnector)
    connector.jobs[job_id]["status"] = "doing"
    connector.jobs[job_id]["worker_id"] = 7


def _status(app: procrastinate.App, job_id: int) -> str:
    connector = app.connector
    assert isinstance(connector, InMemoryConnector)
    return str(connector.jobs[job_id]["status"])


async def _chunk_types(conversation_id: UUID) -> list[str]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id),
        )
        return [str(row.chunk["type"]) for row in rows]


async def _chunks(conversation_id: UUID) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id),
        )
        return [row.chunk for row in rows]


async def test_a_dead_worker_s_turn_is_closed_and_its_job_is_failed(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    job_id = await _defer_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    _hold(queue, job_id)

    await release_dead_turn(conversation_id)

    assert await _chunk_types(conversation_id) == [
        "start",
        "error",
        "data-turn-failed",
        "finish",
        "done",
    ]
    assert _status(queue, job_id) == "failed"


async def test_the_closing_chunks_tell_the_user_to_send_the_message_again(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    job_id = await _defer_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    _hold(queue, job_id)

    await release_dead_turn(conversation_id)

    written = await _chunks(conversation_id)
    assert written[1]["errorText"] == (
        "The worker running this turn stopped, which an out-of-memory kill can "
        "cause. Send the message again to retry."
    )
    assert written[3]["finishReason"] == "error"


async def test_a_job_of_another_thread_is_left_alone(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    job_id = await _defer_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    _hold(queue, job_id)

    await release_dead_turn(uuid4())

    assert await _chunk_types(conversation_id) == ["start"]
    assert _status(queue, job_id) == "doing"


async def test_a_turn_that_already_closed_gets_no_second_terminator(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    await append_chunk(
        conversation_id=conversation_id,
        turn_id=turn_id,
        chunk={"type": "done"},
    )
    job_id = await _defer_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    _hold(queue, job_id)

    await release_dead_turn(conversation_id)

    assert await _chunk_types(conversation_id) == ["start", "done"]
    assert _status(queue, job_id) == "failed"


async def test_the_sweep_releases_every_job_no_live_worker_holds(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    job_id = await _defer_chat_turn(
        queue,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )
    _hold(queue, job_id)

    await release_stalled_jobs()

    assert _status(queue, job_id) == "failed"
    assert await _chunk_types(conversation_id) == [
        "start",
        "error",
        "data-turn-failed",
        "finish",
        "done",
    ]


async def test_a_payload_the_contract_does_not_fit_still_releases_the_job(
    queue: procrastinate.App,
    thread: tuple[UUID, UUID],
) -> None:
    """A host whose payload names no turn keeps its lock released."""
    conversation_id, _user = thread
    turn_id = uuid4()
    await _open_turn(conversation_id, turn_id)
    job_id = await _defer_payload(
        queue,
        conversation_id=conversation_id,
        payload={"body": {"conversationId": str(conversation_id)}},
    )
    _hold(queue, job_id)

    with capture_logs() as logged:
        await release_dead_turn(conversation_id)

    assert [entry["event"] for entry in logged] == [
        "Stalled chat turn carries no readable payload",
        "Released a stalled job",
    ]
    assert _status(queue, job_id) == "failed"
    assert await _chunk_types(conversation_id) == ["start"]


def test_the_published_contract_reads_both_casings() -> None:
    """The two fields the sweep needs, however the host cased them."""
    turn_id, conversation_id = uuid4(), uuid4()

    camel = ChatTurnJobArgs.model_validate(
        {
            "payload": {
                "turnId": str(turn_id),
                "assistantId": "ignored",
                "body": {"conversationId": str(conversation_id), "message": "hi"},
            },
        },
    )
    snake = ChatTurnJobArgs.model_validate(
        {
            "payload": {
                "turn_id": str(turn_id),
                "body": {"conversation_id": str(conversation_id)},
            }
        },
    )

    assert camel.payload.turn_id == turn_id
    assert camel.payload.body.conversation_id == conversation_id
    assert snake == camel
