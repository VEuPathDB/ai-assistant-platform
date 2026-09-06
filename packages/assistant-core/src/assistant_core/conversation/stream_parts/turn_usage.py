"""Payload of the turn-usage part."""

from __future__ import annotations

from pydantic import Field

from assistant_core.platform.pydantic_base import CamelModel


class TurnUsage(CamelModel):
    """Cumulative token + cost totals for the current turn.

    Emitted via ``data-turn-usage`` after each phase completes so the
    composer footer tracks spend in real time. Persisted independently
    via ``MessagesRepository.upsert_message`` so a mid-turn failure still
    leaves the totals in the conversation-detail response.
    """

    total_tokens: int = Field(ge=0)
    cost_usd: str
