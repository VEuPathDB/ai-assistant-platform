"""Headline per-1M-token prices for a (provider, model) pair."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from genai_prices.data_snapshot import get_snapshot
from genai_prices.types import ConditionalPrice, ModelPrice, TieredPrices


@dataclass(frozen=True)
class PerMTokPrices:
    input_: float | None
    cached_input: float | None
    output: float | None


def _flatten_price(value: Decimal | TieredPrices | None) -> float | None:
    """The headline rate of a price, which is the base rate of a tiered one."""
    if value is None:
        return None
    return float(value.base if isinstance(value, TieredPrices) else value)


def _now() -> datetime:
    """The instant a lookup with no explicit one is priced at."""
    return datetime.now(UTC)


def _active_model_price(
    prices: ModelPrice | list[ConditionalPrice],
    at: datetime,
) -> ModelPrice | None:
    """The last price whose constraints hold at ``at``, or None when none do."""
    if isinstance(prices, ModelPrice):
        return prices
    active = [
        entry
        for entry in prices
        if entry.constraint is None or entry.constraint.active(at)
    ]
    return active[-1].prices if active else None


def lookup_per_mtok_prices(
    provider: str,
    model: str,
    *,
    at: datetime | None = None,
) -> PerMTokPrices:
    """Headline $/1M-token for a ``(provider, model)`` pair; ``None`` when unknown.

    ``at`` is the instant the price is read at, and defaults to now in UTC. A
    pair whose price starts on a date, or holds for part of a day, reads the
    price its snapshot constraints make active at that instant.
    """
    when = _now() if at is None else at
    snapshot = get_snapshot()
    for prov in snapshot.providers:
        if prov.id != provider:
            continue
        for mod in prov.models:
            if mod.id != model:
                continue
            active = _active_model_price(mod.prices, when)
            if active is None:
                return PerMTokPrices(input_=None, cached_input=None, output=None)
            return PerMTokPrices(
                input_=_flatten_price(active.input_mtok),
                cached_input=_flatten_price(active.cache_read_mtok),
                output=_flatten_price(active.output_mtok),
            )
    return PerMTokPrices(input_=None, cached_input=None, output=None)
