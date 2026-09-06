"""What one model run cost, in USD."""

from __future__ import annotations

from decimal import Decimal

from genai_prices import calc_price
from pydantic_ai.usage import RunUsage


def cost_for_run(
    *,
    usage: RunUsage,
    model_name: str | None,
    provider_name: str | None,
    provider_url: str | None,
) -> Decimal:
    """Whole-run cost from ``RunUsage``: provider-url first, then by id."""
    if not model_name or not usage.has_values():
        return Decimal(0)
    if provider_url:
        try:
            return calc_price(
                usage,
                model_name,
                provider_api_url=provider_url,
            ).total_price
        except LookupError:
            pass
    try:
        return calc_price(
            usage,
            model_name,
            provider_id=provider_name,
        ).total_price
    except LookupError:
        return Decimal(0)


__all__ = ["cost_for_run"]
