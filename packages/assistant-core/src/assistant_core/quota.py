"""Per-user monthly USD budget, counted per application and per payer.

One budget belongs to a user and rolls over on the first of each month (UTC).
Cost is recorded per application and per payer, and the cap counts the
deployment-paid spend of every application of that user. A host supplies the
limit and decides what a caller at 100% is told.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core.persistence.models import MonthlyUsage
from assistant_core.platform.context import calling_application
from assistant_core.platform.types import PaidBy

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class QuotaStatus:
    """Snapshot of a user's current monthly quota, deployment-paid spend only."""

    used_usd: Decimal
    limit_usd: Decimal
    total_tokens: int
    percent: float
    resets_at: datetime


@dataclass(frozen=True)
class UsageTotals:
    """One payer's spend for a user in the current period."""

    cost_usd: Decimal
    tokens: int


def current_period_start(now: datetime | None = None) -> date:
    """First-of-month UTC date for the current period."""
    ref = now.astimezone(UTC) if now else datetime.now(UTC)
    return date(ref.year, ref.month, 1)


def next_period_start(now: datetime | None = None) -> datetime:
    """First-of-next-month at 00:00 UTC."""
    ref = now.astimezone(UTC) if now else datetime.now(UTC)
    if ref.month == _MONTHS_PER_YEAR:
        return datetime(ref.year + 1, 1, 1, tzinfo=UTC)
    return datetime(ref.year, ref.month + 1, 1, tzinfo=UTC)


async def get_period_totals(
    session: AsyncSession,
    user_id: UUID,
    *,
    paid_by: PaidBy,
) -> UsageTotals:
    """Return one payer's spend for the user in the current period.

    Every application the user drove in the period is summed.
    """
    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(MonthlyUsage.total_cost_usd), 0),
                func.coalesce(func.sum(MonthlyUsage.total_tokens), 0),
            ).where(
                MonthlyUsage.user_id == user_id,
                MonthlyUsage.period_start == current_period_start(),
                MonthlyUsage.paid_by == paid_by,
            ),
        )
    ).one()
    return UsageTotals(cost_usd=Decimal(totals[0]), tokens=int(totals[1]))


async def get_current(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit_usd: Decimal,
) -> QuotaStatus:
    """Return the user's deployment-paid usage for the current monthly period.

    Spend on the user's own key does not count against the limit.
    """
    spent = await get_period_totals(session, user_id, paid_by=PaidBy.DEPLOYMENT)
    percent = float(spent.cost_usd / limit_usd) if limit_usd > 0 else 0.0
    return QuotaStatus(
        used_usd=spent.cost_usd,
        limit_usd=limit_usd,
        total_tokens=spent.tokens,
        percent=percent,
        resets_at=next_period_start(),
    )


async def accumulate(
    session: AsyncSession,
    *,
    user_id: UUID,
    tokens: int,
    cost_usd: Decimal,
    paid_by: PaidBy,
) -> None:
    """Upsert the current-period row of the calling application and payer.

    An unknown payer raises ``ValueError`` before any row is written.
    """
    payer = PaidBy(paid_by)
    if tokens <= 0 and cost_usd <= 0:
        return

    period = current_period_start()
    stmt = (
        pg_insert(MonthlyUsage)
        .values(
            user_id=user_id,
            application_id=calling_application(),
            period_start=period,
            paid_by=payer,
            total_cost_usd=cost_usd,
            total_tokens=tokens,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "application_id", "period_start", "paid_by"],
            set_={
                "total_cost_usd": MonthlyUsage.total_cost_usd + cost_usd,
                "total_tokens": MonthlyUsage.total_tokens + tokens,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await session.execute(stmt)
