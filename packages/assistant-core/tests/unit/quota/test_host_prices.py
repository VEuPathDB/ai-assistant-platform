from collections.abc import Iterator
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage, RunUsage

from assistant_core.cost import cost_for_run
from assistant_core.pricing import (
    HostModelPrice,
    LongPrompt,
    PerMTokPrices,
    TokenPrices,
    install_model_prices,
    lookup_per_mtok_prices,
    reset_model_prices,
)

UNKNOWN = PerMTokPrices(input_=None, cached_input=None, output=None)

SMALL = TokenPrices(
    input_mtok=Decimal("0.10"),
    cache_read_mtok=Decimal("0.01"),
    cache_write_mtok=Decimal("0.125"),
    output_mtok=Decimal("0.50"),
)
LONG = TokenPrices(
    input_mtok=Decimal("0.50"),
    cache_read_mtok=Decimal("0.05"),
    cache_write_mtok=Decimal("0.625"),
    output_mtok=Decimal("2.50"),
)
UNLISTED = HostModelPrice(
    provider="anthropic",
    model="claude-unlisted-9-9",
    prices=SMALL,
    long_prompt=LongPrompt(above_tokens=100_000, prices=LONG),
)


@pytest.fixture(autouse=True)
def _snapshot_prices_after() -> Iterator[None]:
    yield
    reset_model_prices()


def _cost(usage: RunUsage, model: str = "claude-unlisted-9-9") -> Decimal:
    return cost_for_run(
        usage=usage, model_name=model, provider_name="anthropic", provider_url=None
    )


def test_a_model_the_snapshot_lacks_costs_nothing_without_a_host_price() -> None:
    assert _cost(RunUsage(input_tokens=1000, output_tokens=100)) == Decimal(0)
    assert lookup_per_mtok_prices("anthropic", "claude-unlisted-9-9") == UNKNOWN


def test_a_model_the_snapshot_lacks_is_priced_from_the_host_table() -> None:
    install_model_prices([UNLISTED])

    cost = _cost(
        RunUsage(
            input_tokens=11_000,
            cache_read_tokens=4_000,
            cache_write_tokens=2_000,
            output_tokens=1_000,
        )
    )

    assert cost == Decimal("0.00129")
    assert lookup_per_mtok_prices("anthropic", "claude-unlisted-9-9") == (
        PerMTokPrices(input_=0.10, cached_input=0.01, output=0.50)
    )


def test_a_prompt_over_the_threshold_pays_the_long_prompt_prices() -> None:
    install_model_prices([UNLISTED])

    cost = _cost(RunUsage(input_tokens=200_000, output_tokens=1_000))

    assert cost == Decimal("0.1025")


def test_a_registered_price_wins_over_the_snapshot() -> None:
    install_model_prices(
        [
            HostModelPrice(
                provider="openai",
                model="gpt-4o",
                prices=TokenPrices(
                    input_mtok=Decimal(7),
                    cache_read_mtok=Decimal(1),
                    cache_write_mtok=Decimal(7),
                    output_mtok=Decimal(9),
                ),
            )
        ]
    )

    assert lookup_per_mtok_prices("openai", "gpt-4o") == PerMTokPrices(
        input_=7.0, cached_input=1.0, output=9.0
    )
    assert cost_for_run(
        usage=RunUsage(input_tokens=1_000_000),
        model_name="gpt-4o",
        provider_name="openai",
        provider_url=None,
    ) == Decimal(7)


def test_a_model_response_is_priced_from_the_host_table() -> None:
    install_model_prices([UNLISTED])
    response = ModelResponse(
        parts=[TextPart("ok")],
        usage=RequestUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        model_name="claude-unlisted-9-9",
        provider_name="anthropic",
        provider_url="https://api.anthropic.com",
    )

    assert response.cost().total_price == Decimal("3.00")


def test_reset_prices_from_the_snapshot_again() -> None:
    install_model_prices([UNLISTED])
    reset_model_prices()

    assert lookup_per_mtok_prices("anthropic", "claude-unlisted-9-9") == UNKNOWN


def test_a_second_install_replaces_the_first() -> None:
    install_model_prices([UNLISTED])
    install_model_prices([])

    assert lookup_per_mtok_prices("anthropic", "claude-unlisted-9-9") == UNKNOWN


def test_a_provider_the_snapshot_does_not_name_is_refused() -> None:
    with pytest.raises(LookupError, match="no-such-provider"):
        install_model_prices(
            [UNLISTED.model_copy(update={"provider": "no-such-provider"})]
        )


def test_a_long_prompt_needs_a_positive_threshold() -> None:
    with pytest.raises(ValueError, match="above_tokens"):
        LongPrompt(above_tokens=0, prices=LONG)
