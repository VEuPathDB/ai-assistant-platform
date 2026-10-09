from decimal import Decimal

from pydantic_ai.usage import RunUsage

from assistant_core.cost import cost_for_run


def test_a_run_that_carries_its_request_costs_costs_their_sum() -> None:
    usage = RunUsage(input_tokens=400_000, output_tokens=1_000, cost=Decimal("0.03"))

    cost = cost_for_run(
        usage=usage,
        model_name="gpt-4o",
        provider_name="openai",
        provider_url=None,
    )

    assert cost == Decimal("0.03")


def test_a_run_without_request_costs_is_priced_from_its_tokens() -> None:
    usage = RunUsage(input_tokens=1_000_000)

    cost = cost_for_run(
        usage=usage,
        model_name="gpt-4o",
        provider_name="openai",
        provider_url=None,
    )

    assert cost == Decimal("2.5")


def test_a_run_with_no_tokens_costs_nothing() -> None:
    assert cost_for_run(
        usage=RunUsage(),
        model_name="gpt-4o",
        provider_name="openai",
        provider_url=None,
    ) == Decimal(0)
