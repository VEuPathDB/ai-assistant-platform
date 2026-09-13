"""A durable call keeps its row only when the queue accepted its job."""

from __future__ import annotations

from asyncio import CancelledError, create_task, sleep
from collections.abc import AsyncGenerator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import procrastinate
import pytest
from procrastinate import types
from procrastinate.exceptions import ConnectorException
from procrastinate.testing import InMemoryConnector
from pydantic_ai.exceptions import CallDeferred
from sqlalchemy.exc import SQLAlchemyError

from assistant_core.graph.turn_state import DurableDeferral
from assistant_core.tasks import decorator
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.declaration import declare_durable_tool, empty_durable_tools
from assistant_core.tasks.decorator import durable_tool

CRUNCH_SECONDS = 30
REFUSAL = "the queue is not reachable"
DATABASE_REFUSAL = "the database is not reachable"
SLOW_DEFER_SECONDS = 10
SLOW_DISCARD_SECONDS = 0.05


@dataclass
class _Deps:
    """The identity a durable dispatch reads off the agent's deps."""

    conversation_id: UUID
    user_id: UUID
    durable_deferrals: dict[str, DurableDeferral] = field(default_factory=dict)


@dataclass
class _Ctx:
    """The run context the decorator parses its invocation from."""

    deps: _Deps
    tool_call_id: str


class _RefusingConnector(InMemoryConnector):
    """A queue that refuses every defer."""

    async def defer_jobs_all(
        self,
        jobs: list[types.JobToDefer],
    ) -> list[dict[str, Any]]:
        del jobs
        raise ConnectorException(REFUSAL)


class _CancellingConnector(InMemoryConnector):
    """A queue whose defer is cancelled under a stopping process."""

    async def defer_jobs_all(
        self,
        jobs: list[types.JobToDefer],
    ) -> list[dict[str, Any]]:
        del jobs
        raise CancelledError


@pytest.fixture
def rows(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """The task rows the decorator wrote, instead of a database."""
    written: list[UUID] = []

    async def fake_create(**kwargs: Any) -> UUID:
        del kwargs
        task_id = uuid4()
        written.append(task_id)
        return task_id

    async def fake_discard(*, task_id: UUID) -> None:
        written.remove(task_id)

    monkeypatch.setattr(decorator, "create_background_task", fake_create)
    monkeypatch.setattr(decorator, "discard_background_task", fake_discard)
    return written


@pytest.fixture
def chunks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The stream chunks the decorator emitted, instead of a graph run."""
    emitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        decorator,
        "get_stream_writer",
        lambda: emitted.append,
    )
    return emitted


@pytest.fixture
def crunch() -> Iterator[Callable[..., Any]]:
    """One declared durable tool, decorated the way a host decorates its own."""
    with empty_durable_tools():
        tool = declare_durable_tool(
            tool_name="crunch",
            estimated_duration_seconds=CRUNCH_SECONDS,
        )

        @durable_tool(tool)
        async def _crunch(ctx: _Ctx, n: int) -> str:
            del ctx, n
            return ""

        yield _crunch


@pytest.fixture
async def accepting_queue() -> AsyncGenerator[InMemoryConnector]:
    """A queue that keeps the jobs it accepts in memory."""
    async for connector in _installed_queue(InMemoryConnector()):
        yield connector


@pytest.fixture
async def refusing_queue() -> AsyncGenerator[InMemoryConnector]:
    """A queue whose defer raises."""
    async for connector in _installed_queue(_RefusingConnector()):
        yield connector


class _SlowConnector(InMemoryConnector):
    """A queue whose defer is still in flight when the caller is cancelled."""

    async def defer_jobs_all(
        self,
        jobs: list[types.JobToDefer],
    ) -> list[dict[str, Any]]:
        del jobs
        await sleep(SLOW_DEFER_SECONDS)
        return []


@pytest.fixture
async def slow_queue() -> AsyncGenerator[InMemoryConnector]:
    """A queue whose defer has not answered yet."""
    async for connector in _installed_queue(_SlowConnector()):
        yield connector


@pytest.fixture
async def cancelling_queue() -> AsyncGenerator[InMemoryConnector]:
    """A queue whose defer is cancelled."""
    async for connector in _installed_queue(_CancellingConnector()):
        yield connector


async def _installed_queue(
    connector: InMemoryConnector,
) -> AsyncGenerator[InMemoryConnector]:
    app = procrastinate.App(connector=connector)
    install_task_app(app)
    try:
        async with app.open_async():
            yield connector
    finally:
        reset_task_app()


def _context() -> _Ctx:
    return _Ctx(
        deps=_Deps(conversation_id=uuid4(), user_id=uuid4()),
        tool_call_id="call-1",
    )


async def test_an_accepted_defer_leaves_one_row_and_announces_the_task(
    crunch: Callable[..., Any],
    rows: list[UUID],
    chunks: list[dict[str, Any]],
    accepting_queue: InMemoryConnector,
) -> None:
    ctx = _context()

    with pytest.raises(CallDeferred):
        await crunch(ctx, n=2)

    assert len(rows) == 1
    assert [job["task_name"] for job in accepting_queue.jobs.values()] == [
        "durable:crunch",
    ]
    assert [chunk["chunk"]["type"] for chunk in chunks] == [
        "data-background-task-started",
    ]
    assert list(ctx.deps.durable_deferrals) == ["call-1"]


async def test_a_defer_the_queue_refuses_leaves_no_row_and_raises(
    crunch: Callable[..., Any],
    rows: list[UUID],
    chunks: list[dict[str, Any]],
    refusing_queue: InMemoryConnector,
) -> None:
    ctx = _context()

    with pytest.raises(ConnectorException):
        await crunch(ctx, n=2)

    assert rows == []
    assert refusing_queue.jobs == {}
    assert chunks == []
    assert ctx.deps.durable_deferrals == {}


async def test_a_cancelled_defer_leaves_no_row_and_cancels_the_call(
    crunch: Callable[..., Any],
    rows: list[UUID],
    chunks: list[dict[str, Any]],
    cancelling_queue: InMemoryConnector,
) -> None:
    ctx = _context()

    with pytest.raises(CancelledError):
        await crunch(ctx, n=2)

    assert rows == []
    assert cancelling_queue.jobs == {}
    assert chunks == []


async def test_a_removal_that_fails_rides_the_error_the_queue_raised(
    crunch: Callable[..., Any],
    rows: list[UUID],
    refusing_queue: InMemoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del refusing_queue

    async def failing_discard(*, task_id: UUID) -> None:
        del task_id
        raise SQLAlchemyError(DATABASE_REFUSAL)

    monkeypatch.setattr(decorator, "discard_background_task", failing_discard)

    with pytest.raises(ConnectorException) as caught:
        await crunch(_context(), n=2)

    assert str(caught.value) == REFUSAL
    assert caught.value.__notes__ == [
        f"the durable task row was not removed: {DATABASE_REFUSAL}",
    ]
    assert len(rows) == 1


async def test_a_second_cancellation_does_not_interrupt_the_removal(
    crunch: Callable[..., Any],
    rows: list[UUID],
    slow_queue: InMemoryConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del slow_queue

    async def slow_discard(*, task_id: UUID) -> None:
        await sleep(SLOW_DISCARD_SECONDS)
        rows.remove(task_id)

    monkeypatch.setattr(decorator, "discard_background_task", slow_discard)
    call = create_task(crunch(_context(), n=2))
    await sleep(SLOW_DISCARD_SECONDS)

    call.cancel()
    await sleep(0)
    await sleep(0)
    call.cancel()
    with pytest.raises(CancelledError):
        await call
    await sleep(SLOW_DISCARD_SECONDS * 4)

    assert rows == []
