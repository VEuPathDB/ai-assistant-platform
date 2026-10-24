from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, TextDeltaChunk
from sqlalchemy import text
from tests.conftest import seed_thread
from tests.sse import Frame, read_stream
from tests.synthetic import dump_chunk

from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.platform.db import async_session_factory

TAILS = 10
ATTACH_SECONDS = 0.5
READ_TIMEOUT_SECONDS = 20.0
_LISTENING = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND query LIKE 'LISTEN %'",
)
_DROP_LISTENERS = text(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname = current_database() AND query LIKE 'LISTEN %'",
)

pytestmark = pytest.mark.usefixtures("patch_app_db_engine", "db_cleaner")


async def _threads(count: int) -> list[UUID]:
    threads = [uuid4() for _ in range(count)]
    for thread in threads:
        await seed_thread(conversation_id=thread, user_id=uuid4(), site_id="plasmodb")
    return threads


async def _listening() -> int:
    async with async_session_factory() as session:
        return int((await session.execute(_LISTENING)).scalar_one())


async def _finish(thread: UUID, delta: str) -> None:
    writer = ChatEventWriter(conversation_id=thread, turn_id=uuid4())
    await writer.write(dump_chunk(TextDeltaChunk(id="t1", delta=delta)))
    await writer.write(dump_chunk(DoneChunk()))


def _deltas(frames: list[Frame]) -> list[str]:
    return [
        frame.chunk()["delta"]
        for frame in frames
        if frame.data is not None and not frame.is_done
    ]


async def test_concurrent_tails_listen_on_one_connection() -> None:
    threads = await _threads(TAILS)
    readers = [asyncio.create_task(read_stream(thread)) for thread in threads]
    await asyncio.sleep(ATTACH_SECONDS)
    listening = await _listening()

    for thread in threads:
        await _finish(thread, f"reply {thread.hex[:6]}")
    async with asyncio.timeout(READ_TIMEOUT_SECONDS):
        streams = await asyncio.gather(*readers)

    assert listening == 1
    assert [_deltas(frames) for frames in streams] == [
        [f"reply {thread.hex[:6]}"] for thread in threads
    ]


async def test_a_tail_survives_its_listener_being_dropped() -> None:
    (thread,) = await _threads(1)
    reader = asyncio.create_task(read_stream(thread))
    await asyncio.sleep(ATTACH_SECONDS)
    async with async_session_factory() as session:
        await session.execute(_DROP_LISTENERS)
        await session.commit()
    await asyncio.sleep(ATTACH_SECONDS)

    await _finish(thread, "after the drop")
    async with asyncio.timeout(READ_TIMEOUT_SECONDS):
        frames = await reader

    assert _deltas(frames) == ["after the drop"]
