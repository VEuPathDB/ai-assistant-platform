"""One chat turn is one job, on the runtime's queue, locked on its thread."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector

from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.chat_turn import defer_chat_turn


@pytest.fixture
async def connector() -> AsyncGenerator[InMemoryConnector]:
    """A queue that keeps its jobs in memory."""
    in_memory = InMemoryConnector()
    app = procrastinate.App(connector=in_memory)
    install_task_app(app)
    try:
        async with app.open_async():
            yield in_memory
    finally:
        reset_task_app()


async def test_a_deferred_turn_names_the_runtimes_task_and_locks_its_thread(
    connector: InMemoryConnector,
) -> None:
    conversation_id = uuid4()
    payload = {"turnId": str(uuid4()), "body": {"conversationId": str(conversation_id)}}

    await defer_chat_turn(conversation_id=conversation_id, payload=payload)

    deferred = list(connector.jobs.values())
    assert [job["task_name"] for job in deferred] == ["chat_turn:run"]
    assert [job["queue_name"] for job in deferred] == ["chat_turn"]
    assert [job["lock"] for job in deferred] == [str(conversation_id)]
    assert [job["args"] for job in deferred] == [{"payload": payload}]


async def test_a_payload_the_stalled_job_sweep_cannot_read_is_refused(
    connector: InMemoryConnector,
) -> None:
    conversation_id = uuid4()

    with pytest.raises(ValueError, match="turnId"):
        await defer_chat_turn(
            conversation_id=conversation_id,
            payload={"body": {"conversationId": str(conversation_id)}},
        )

    assert connector.jobs == {}
