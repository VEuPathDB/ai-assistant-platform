"""Headline prices come from the packaged snapshot, at a caller-chosen instant."""

from datetime import UTC, datetime

import pytest

from assistant_core import pricing
from assistant_core.pricing import PerMTokPrices, lookup_per_mtok_prices

UNKNOWN = PerMTokPrices(input_=None, cached_input=None, output=None)

BEFORE_GEMINI_RAISE = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
AFTER_GEMINI_RAISE = datetime(2027, 6, 15, 12, 0, tzinfo=UTC)
INSIDE_DEEPSEEK_WINDOW = datetime(2026, 6, 15, 8, 0, tzinfo=UTC)
OUTSIDE_DEEPSEEK_WINDOW = datetime(2026, 6, 15, 20, 0, tzinfo=UTC)
AFTER_LUNA_REPRICE = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_a_model_with_one_price_reads_that_price() -> None:
    prices = lookup_per_mtok_prices("openai", "gpt-4o", at=BEFORE_GEMINI_RAISE)

    assert prices == PerMTokPrices(input_=2.5, cached_input=1.25, output=10.0)


def test_a_price_whose_start_date_has_not_arrived_is_not_used() -> None:
    """The snapshot gives this pair a second price that starts in 2027."""
    prices = lookup_per_mtok_prices(
        "google",
        "gemini-3.6-flash",
        at=BEFORE_GEMINI_RAISE,
    )

    assert prices == PerMTokPrices(input_=0.75, cached_input=0.075, output=3.75)


def test_a_price_whose_start_date_has_arrived_is_used() -> None:
    """The same pair reads the dated price at an instant after its start date."""
    prices = lookup_per_mtok_prices(
        "google",
        "gemini-3.6-flash",
        at=AFTER_GEMINI_RAISE,
    )

    assert prices == PerMTokPrices(input_=1.5, cached_input=0.15, output=7.5)


def test_a_daily_window_price_is_used_inside_its_window() -> None:
    """This pair prices a daily off-peak window between 00:30 and 16:30 UTC."""
    prices = lookup_per_mtok_prices(
        "deepseek",
        "deepseek-chat",
        at=INSIDE_DEEPSEEK_WINDOW,
    )

    assert prices == PerMTokPrices(input_=0.27, cached_input=0.07, output=1.1)


def test_a_daily_window_price_is_not_used_outside_its_window() -> None:
    prices = lookup_per_mtok_prices(
        "deepseek",
        "deepseek-chat",
        at=OUTSIDE_DEEPSEEK_WINDOW,
    )

    assert prices == PerMTokPrices(input_=0.135, cached_input=0.035, output=0.55)


def test_a_tiered_price_reads_its_base_rate() -> None:
    """This pair prices in tiers, and its dated price starts in July 2026."""
    prices = lookup_per_mtok_prices("openai", "gpt-5.6-luna", at=AFTER_LUNA_REPRICE)

    assert prices == PerMTokPrices(input_=0.2, cached_input=0.02, output=1.2)


def test_no_instant_reads_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lookup with no instant prices at the moment the module reads."""
    monkeypatch.setattr(pricing, "_now", lambda: AFTER_GEMINI_RAISE)

    prices = lookup_per_mtok_prices("google", "gemini-3.6-flash")

    assert prices == PerMTokPrices(input_=1.5, cached_input=0.15, output=7.5)


def test_a_model_the_provider_does_not_list_reads_as_unknown() -> None:
    assert lookup_per_mtok_prices("openai", "gpt-not-a-model") == UNKNOWN


def test_a_provider_the_snapshot_does_not_carry_reads_as_unknown() -> None:
    assert lookup_per_mtok_prices("no-such-provider", "gpt-4o") == UNKNOWN
