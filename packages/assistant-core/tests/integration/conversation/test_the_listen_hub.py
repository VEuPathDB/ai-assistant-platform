from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, TextDeltaChunk
from sqlalchemy import text
from sqlalchemy.engine import make_url
from tests.conftest import seed_thread
from tests.sse import Frame, parse_frame
from tests.synthetic import dump_chunk

from assistant_core.conversation.event_stream import iter_sse
from assistant_core.conversation.event_writer import ChatEventWriter
from assistant_core.conversation.listen_hub import (
    KEEPALIVES,
    ListenHub,
    close_listen_hub,
    listen_hub,
)
from assistant_core.platform.db import async_session_factory

ATTACH_SECONDS = 0.5
WAIT_SECONDS = 10.0
_LISTENING = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND query LIKE 'LISTEN %'",
)
_DROP_LISTENERS = text(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname = current_database() AND query LIKE 'LISTEN %'",
)
_NOTIFY = text("SELECT pg_notify(:channel, :payload)")

pytestmark = pytest.mark.usefixtures("patch_app_db_engine", "db_cleaner")


def _dsn() -> str:
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def _sql(statement: object, **params: str) -> object:
    async with async_session_factory() as session:
        result = await session.execute(statement, params)
        value = result.scalar()
        await session.commit()
        return value


async def _thread() -> UUID:
    thread = uuid4()
    await seed_thread(conversation_id=thread, user_id=uuid4(), site_id="plasmodb")
    return thread


async def _write(thread: UUID, *chunks: object) -> None:
    writer = ChatEventWriter(conversation_id=thread, turn_id=uuid4())
    for chunk in chunks:
        await writer.write(dump_chunk(chunk))


async def test_a_row_written_while_the_listener_is_down_reaches_the_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = await _thread()
    frames: list[Frame] = []
    delivered = asyncio.Event()

    async def _read() -> None:
        async for raw in iter_sse(conversation_id=thread, after=0):
            frame = parse_frame(raw)
            frames.append(frame)
            if frame.data is not None and not frame.is_done:
                delivered.set()

    reader = asyncio.create_task(_read())
    await asyncio.sleep(ATTACH_SECONDS)
    reopening, released = asyncio.Event(), asyncio.Event()
    opened = ListenHub._open

    async def _held_open(hub: ListenHub) -> asyncpg.Connection:
        reopening.set()
        await released.wait()
        return await opened(hub)

    monkeypatch.setattr(ListenHub, "_open", _held_open)
    await _sql(_DROP_LISTENERS)
    async with asyncio.timeout(WAIT_SECONDS):
        await reopening.wait()
    await _write(thread, TextDeltaChunk(id="t1", delta="during the outage"))
    released.set()
    async with asyncio.timeout(WAIT_SECONDS):
        await delivered.wait()
    await _write(thread, DoneChunk())
    async with asyncio.timeout(WAIT_SECONDS):
        await reader

    assert [
        frame.chunk()["delta"]
        for frame in frames
        if frame.data is not None and not frame.is_done
    ] == ["during the outage"]


async def test_a_failed_listen_leaves_the_channel_free_to_listen_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = ListenHub(_dsn())
    added = asyncpg.Connection.add_listener
    refusals = [ConnectionError("the server refused LISTEN")]

    async def _refuse_once(
        connection: asyncpg.Connection, channel: str, callback: object
    ) -> None:
        if refusals:
            raise refusals.pop()
        await added(connection, channel, callback)

    monkeypatch.setattr(asyncpg.Connection, "add_listener", _refuse_once)
    try:
        with pytest.raises(ConnectionError):
            await hub.subscribe("hub-test")
        queue = await hub.subscribe("hub-test")
        await _sql(_NOTIFY, channel="hub-test", payload="7")
        async with asyncio.timeout(WAIT_SECONDS):
            delivered = await queue.get()
    finally:
        await hub.close()

    assert delivered == 7


async def test_closing_the_hub_closes_its_connection() -> None:
    hub = listen_hub(_dsn())
    await hub.subscribe("hub-close-test")
    listening = await _sql(_LISTENING)

    await close_listen_hub()

    assert (listening, await _sql(_LISTENING)) == (1, 0)
    assert listen_hub(_dsn()) is not hub
    await close_listen_hub()


async def test_the_hub_connection_keeps_its_socket_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[asyncpg.Connection] = []
    connect = asyncpg.connect

    async def _spy(*args: object, **kwargs: object) -> asyncpg.Connection:
        connection = await connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(asyncpg, "connect", _spy)
    hub = ListenHub(_dsn())
    try:
        await hub.subscribe("hub-keepalive-test")
        on_the_hub = {
            name: await opened[0].fetchval(f"SHOW {name}") for name in KEEPALIVES
        }
    finally:
        await hub.close()

    assert on_the_hub == KEEPALIVES
