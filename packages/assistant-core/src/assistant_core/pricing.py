"""Headline per-1M-token prices for a (provider, model) pair."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from genai_prices import data
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    Provider,
    Tier,
    TieredPrices,
)
from pydantic import BaseModel, ConfigDict, PositiveInt


class TokenPrices(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_mtok: Decimal
    cache_read_mtok: Decimal
    cache_write_mtok: Decimal
    output_mtok: Decimal


class LongPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    above_tokens: PositiveInt
    prices: TokenPrices


class HostModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    prices: TokenPrices
    long_prompt: LongPrompt | None = None

    def _rate(self, base: Decimal, long: Decimal) -> Decimal | TieredPrices:
        if self.long_prompt is None:
            return base
        return TieredPrices(
            base=base, tiers=[Tier(start=self.long_prompt.above_tokens, price=long)]
        )

    def model_info(self) -> ModelInfo:
        base = self.prices
        long = base if self.long_prompt is None else self.long_prompt.prices
        return ModelInfo(
            id=self.model,
            match=ClauseEquals(equals=self.model),
            prices=ModelPrice(
                input_mtok=self._rate(base.input_mtok, long.input_mtok),
                cache_read_mtok=self._rate(base.cache_read_mtok, long.cache_read_mtok),
                cache_write_mtok=self._rate(
                    base.cache_write_mtok, long.cache_write_mtok
                ),
                output_mtok=self._rate(base.output_mtok, long.output_mtok),
            ),
        )


def _with_host_models(
    provider: Provider, added: dict[str, list[ModelInfo]]
) -> Provider:
    models = added.get(provider.id)
    if models is None:
        return provider
    return dataclasses.replace(provider, models=[*models, *provider.models])


def install_model_prices(prices: Iterable[HostModelPrice]) -> None:
    added: dict[str, list[ModelInfo]] = {}
    for price in prices:
        added.setdefault(price.provider, []).append(price.model_info())
    unknown = sorted(set(added) - {provider.id for provider in data.providers})
    if unknown:
        msg = f"the price snapshot names no provider {', '.join(unknown)}"
        raise LookupError(msg)
    set_custom_snapshot(
        DataSnapshot(
            providers=[_with_host_models(p, added) for p in data.providers],
            from_auto_update=False,
        )
    )


def reset_model_prices() -> None:
    set_custom_snapshot(None)


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
