"""Usage is attributed per application; the monthly cap stays per user."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from tests.conftest import seed_host_user

from assistant_core import quota
from assistant_core.persistence.models import MonthlyUsage
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory

HOME = "pathfinder"
OTHER = "companion"
LIMIT = Decimal("10.0")


@pytest.fixture
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


async def _accumulate(application_id: str, user_id: UUID, cost: str) -> None:
    token = application_id_ctx.set(application_id)
    try:
        async with async_session_factory() as session:
            await quota.accumulate(
                session,
                user_id=user_id,
                tokens=100,
                cost_usd=Decimal(cost),
            )
            await session.commit()
    finally:
        application_id_ctx.reset(token)


async def _rows(user_id: UUID) -> list[MonthlyUsage]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(MonthlyUsage).where(MonthlyUsage.user_id == user_id),
        )
        return list(result.scalars().all())


async def test_each_application_gets_its_own_usage_row(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _accumulate(HOME, user_id, "1.50")
    await _accumulate(OTHER, user_id, "2.25")

    by_application = {
        row.application_id: row.total_cost_usd for row in await _rows(user_id)
    }

    assert by_application == {HOME: Decimal("1.50"), OTHER: Decimal("2.25")}


async def test_the_cap_sums_every_application_of_one_user(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _accumulate(HOME, user_id, "1.50")
    await _accumulate(OTHER, user_id, "2.25")

    async with async_session_factory() as session:
        status = await quota.get_current(session, user_id, limit_usd=LIMIT)

    assert status.used_usd == Decimal("3.75")
    assert status.total_tokens == 200
    assert status.limit_usd == LIMIT
    assert status.percent == pytest.approx(0.375)


async def test_a_second_charge_from_one_application_adds_to_its_own_row(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _accumulate(OTHER, user_id, "1.00")
    await _accumulate(OTHER, user_id, "0.50")

    rows = await _rows(user_id)

    assert len(rows) == 1
    assert rows[0].total_cost_usd == Decimal("1.50")


async def test_a_user_who_spent_nothing_reads_as_empty(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    async with async_session_factory() as session:
        status = await quota.get_current(session, user_id, limit_usd=LIMIT)

    assert status.used_usd == Decimal(0)
    assert status.total_tokens == 0
    assert status.percent == 0.0


async def test_a_charge_of_nothing_writes_no_row(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    async with async_session_factory() as session:
        await quota.accumulate(session, user_id=user_id, tokens=0, cost_usd=Decimal(0))
        await session.commit()

    assert await _rows(user_id) == []
