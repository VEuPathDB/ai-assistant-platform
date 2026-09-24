"""Every usage row names who paid, and the cap counts only the deployment's spend."""

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
from assistant_core.platform.types import PaidBy

HOME = "pathfinder"
LIMIT = Decimal("10.0")


@pytest.fixture
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


async def _charge(user_id: UUID, cost: str, tokens: int, paid_by: PaidBy) -> None:
    async with async_session_factory() as session:
        await quota.accumulate(
            session,
            user_id=user_id,
            tokens=tokens,
            cost_usd=Decimal(cost),
            paid_by=paid_by,
        )
        await session.commit()


async def _rows(user_id: UUID) -> list[MonthlyUsage]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(MonthlyUsage).where(MonthlyUsage.user_id == user_id),
        )
        return list(result.scalars().all())


async def test_each_payer_keeps_its_own_row(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _charge(user_id, "1.50", 100, PaidBy.DEPLOYMENT)
    await _charge(user_id, "3.40", 700, PaidBy.USER)
    await _charge(user_id, "0.60", 50, PaidBy.USER)

    by_payer = {
        row.paid_by: (row.total_cost_usd, row.total_tokens)
        for row in await _rows(user_id)
    }

    assert by_payer == {
        PaidBy.DEPLOYMENT: (Decimal("1.50"), 100),
        PaidBy.USER: (Decimal("4.00"), 750),
    }


async def test_a_user_paid_charge_does_not_count_toward_the_cap(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _charge(user_id, "1.50", 100, PaidBy.DEPLOYMENT)
    await _charge(user_id, "30.00", 9000, PaidBy.USER)

    async with async_session_factory() as session:
        status = await quota.get_current(session, user_id, limit_usd=LIMIT)

    assert status.used_usd == Decimal("1.50")
    assert status.total_tokens == 100
    assert status.percent == pytest.approx(0.15)


async def test_the_two_payers_read_as_two_totals(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _charge(user_id, "1.50", 100, PaidBy.DEPLOYMENT)
    await _charge(user_id, "3.40", 700, PaidBy.USER)

    async with async_session_factory() as session:
        deployment = await quota.get_period_totals(
            session, user_id, paid_by=PaidBy.DEPLOYMENT
        )
        user = await quota.get_period_totals(session, user_id, paid_by=PaidBy.USER)

    assert deployment == quota.UsageTotals(cost_usd=Decimal("1.50"), tokens=100)
    assert user == quota.UsageTotals(cost_usd=Decimal("3.40"), tokens=700)


async def test_a_payer_with_no_spend_reads_as_zero(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    await _charge(user_id, "1.50", 100, PaidBy.DEPLOYMENT)

    async with async_session_factory() as session:
        user = await quota.get_period_totals(session, user_id, paid_by=PaidBy.USER)

    assert user == quota.UsageTotals(cost_usd=Decimal(0), tokens=0)


async def test_an_unknown_payer_is_refused_before_a_row_is_written(
    db_cleaner: None,
    patch_app_db_engine: None,
    under_home: None,
) -> None:
    """A host with no type checker reaches the runtime check, not the database."""
    del db_cleaner, patch_app_db_engine, under_home
    user_id = uuid4()
    await seed_host_user(user_id)

    async with async_session_factory() as session:
        with pytest.raises(ValueError, match="'house' is not a valid PaidBy"):
            await quota.accumulate(
                session,
                user_id=user_id,
                tokens=10,
                cost_usd=Decimal("0.10"),
                paid_by="house",
            )

    assert await _rows(user_id) == []
