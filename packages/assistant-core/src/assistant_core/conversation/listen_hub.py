from __future__ import annotations

import asyncio
import contextlib

import asyncpg

from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

_LOST = (OSError, asyncpg.PostgresError, asyncpg.InterfaceError)
_FIRST_RETRY_SECONDS = 0.1
_LAST_RETRY_SECONDS = 5.0
_WAKE = 0
KEEPALIVES = {
    "tcp_keepalives_idle": "30",
    "tcp_keepalives_interval": "10",
    "tcp_keepalives_count": "3",
}


class ListenHub:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: asyncpg.Connection | None = None
        self._queues: dict[str, set[asyncio.Queue[int]]] = {}
        self._guard = asyncio.Lock()
        self._relistening: asyncio.Task[None] | None = None
        self._closed = False

    async def subscribe(self, channel: str) -> asyncio.Queue[int]:
        queue: asyncio.Queue[int] = asyncio.Queue()
        async with self._guard:
            connection = await self._open()
            if channel not in self._queues:
                await connection.add_listener(channel, self._notified)
                self._queues[channel] = set()
            self._queues[channel].add(queue)
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue[int]) -> None:
        async with self._guard:
            waiting = self._queues.get(channel)
            if waiting is None:
                return
            waiting.discard(queue)
            if waiting:
                return
            del self._queues[channel]
            connection = self._connection
            if connection is not None and not connection.is_closed():
                with contextlib.suppress(*_LOST):
                    await connection.remove_listener(channel, self._notified)

    async def _open(self) -> asyncpg.Connection:
        connection = self._connection
        if connection is not None and not connection.is_closed():
            return connection
        connection = await asyncpg.connect(dsn=self._dsn, server_settings=KEEPALIVES)
        connection.add_termination_listener(self._lost)
        for channel in self._queues:
            await connection.add_listener(channel, self._notified)
        self._connection = connection
        return connection

    def _notified(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        del connection, pid
        try:
            event_id = int(payload)
        except ValueError:
            logger.warning("pg_notify payload not an int", payload=payload)
            return
        for queue in self._queues.get(channel, ()):
            queue.put_nowait(event_id)

    async def close(self) -> None:
        self._closed = True
        if self._relistening is not None:
            self._relistening.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._relistening
        connection, self._connection = self._connection, None
        if connection is not None and not connection.is_closed():
            await connection.close()

    def _lost(self, connection: object) -> None:
        del connection
        self._connection = None
        if self._closed:
            return
        logger.warning(
            "the shared LISTEN connection dropped", channels=len(self._queues)
        )
        if not self._queues:
            return
        if self._relistening is not None and not self._relistening.done():
            return
        self._relistening = asyncio.get_running_loop().create_task(self._relisten())

    async def _relisten(self) -> None:
        delay = _FIRST_RETRY_SECONDS
        while self._queues:
            try:
                async with self._guard:
                    await self._open()
            except _LOST:
                await asyncio.sleep(delay)
                delay = min(delay * 2, _LAST_RETRY_SECONDS)
                continue
            for queues in self._queues.values():
                for queue in queues:
                    queue.put_nowait(_WAKE)
            return


_hubs: dict[asyncio.AbstractEventLoop, ListenHub] = {}


def listen_hub(dsn: str) -> ListenHub:
    loop = asyncio.get_running_loop()
    hub = _hubs.get(loop)
    if hub is None:
        hub = ListenHub(dsn)
        _hubs[loop] = hub
    return hub


async def close_listen_hub() -> None:
    hub = _hubs.pop(asyncio.get_running_loop(), None)
    if hub is not None:
        await hub.close()


__all__ = ["KEEPALIVES", "ListenHub", "close_listen_hub", "listen_hub"]
