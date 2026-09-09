"""The thread log keeps the newest not-due update, per lane."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.tasks import progress
from assistant_core.tasks.progress import (
    TaskProgressEmitter,
    _PendingProgress,
    _ThreadLog,
)


def _row(percent: float) -> _PendingProgress:
    return _PendingProgress(percent=percent, message="working", data=None)


def _no_session() -> AsyncSession:
    msg = "this test writes nothing to the database"
    raise AssertionError(msg)


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The chunks the thread log appended, instead of a database."""
    rows: list[dict[str, Any]] = []

    async def fake_append(*, conversation_id: object, chunk: dict[str, Any]) -> int:
        del conversation_id
        rows.append(chunk)
        return len(rows)

    monkeypatch.setattr(progress, "append_chunk", fake_append)
    return rows


async def test_the_first_update_reaches_the_log_and_the_next_small_one_waits(
    written: list[dict[str, Any]],
) -> None:
    log = _ThreadLog(conversation_id=uuid4(), task_id=uuid4())

    await log.offer(_row(0.10))
    await log.offer(_row(0.12))

    assert [chunk["data"]["percent"] for chunk in written] == [0.10]


async def test_an_advance_of_five_points_reaches_the_log(
    written: list[dict[str, Any]],
) -> None:
    log = _ThreadLog(conversation_id=uuid4(), task_id=uuid4())

    await log.offer(_row(0.10))
    await log.offer(_row(0.15))

    assert [chunk["data"]["percent"] for chunk in written] == [0.10, 0.15]


async def test_ten_seconds_of_silence_lets_a_small_advance_through(
    written: list[dict[str, Any]],
) -> None:
    log = _ThreadLog(conversation_id=uuid4(), task_id=uuid4())

    await log.offer(_row(0.10))
    log.written_at -= 10.0
    await log.offer(_row(0.11))

    assert [chunk["data"]["percent"] for chunk in written] == [0.10, 0.11]


async def test_closing_writes_the_newest_update_the_log_does_not_hold(
    written: list[dict[str, Any]],
) -> None:
    log = _ThreadLog(conversation_id=uuid4(), task_id=uuid4())

    await log.offer(_row(0.10))
    await log.offer(_row(0.12))
    await log.write_last()

    assert [chunk["data"]["percent"] for chunk in written] == [0.10, 0.12]


async def test_a_concurrent_offer_survives_a_slow_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    release.set()
    rows: list[dict[str, Any]] = []

    async def fake_append(*, conversation_id: object, chunk: dict[str, Any]) -> int:
        del conversation_id
        await release.wait()
        rows.append(chunk)
        return len(rows)

    monkeypatch.setattr(progress, "append_chunk", fake_append)
    log = _ThreadLog(conversation_id=uuid4(), task_id=uuid4())

    await log.offer(_row(0.10))
    release.clear()
    due = asyncio.ensure_future(log.offer(_row(0.15)))
    await asyncio.sleep(0)
    await log.offer(_row(0.12))
    release.set()
    await due
    await log.write_last()

    assert [chunk["data"]["percent"] for chunk in rows] == [0.10, 0.15, 0.12]


async def test_a_lane_suffixes_the_id_of_every_chunk_it_writes(
    written: list[dict[str, Any]],
) -> None:
    task_id = uuid4()
    log = _ThreadLog(conversation_id=uuid4(), task_id=task_id, lane="v3")

    await log.offer(_row(0.10))

    assert [chunk["id"] for chunk in written] == [f"{task_id}:v3"]
    assert written[0]["data"]["taskId"] == str(task_id)


async def test_every_lane_keeps_a_budget_and_an_id_of_its_own(
    written: list[dict[str, Any]],
) -> None:
    task_id = uuid4()
    parent = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=uuid4(),
        session_factory=_no_session,
    )

    for variant in ("v0", "v1", "v2", "v3", "v4"):
        child = parent.scoped(variantId=variant)
        await child._thread_log.offer(_row(0.0))

    assert [chunk["id"] for chunk in written] == [f"{task_id}:v{n}" for n in range(5)]


async def test_a_child_that_scopes_nothing_keeps_the_bare_task_id(
    written: list[dict[str, Any]],
) -> None:
    task_id = uuid4()
    parent = TaskProgressEmitter(
        task_id=task_id,
        conversation_id=uuid4(),
        session_factory=_no_session,
    )

    await parent.scoped()._thread_log.offer(_row(0.0))

    assert [chunk["id"] for chunk in written] == [str(task_id)]
