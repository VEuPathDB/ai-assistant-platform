"""What the turn used reaches the assistant's own accounting, once."""

from __future__ import annotations

from decimal import Decimal

from tests.synthetic import ADD_PROMPT, PLAIN_PROMPT, SyntheticRuntime, TurnOutcome


def _reported_tokens(outcome: TurnOutcome) -> int:
    usage = [c for c in outcome.chunks if c["type"] == "data-turn-usage"]
    assert len(usage) == 1
    return int(usage[0]["data"]["totalTokens"])


async def test_the_assistant_is_charged_once_for_the_turn_it_ran(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)

    assert len(runtime.ledger.charges) == 1
    user_id, tokens, cost = runtime.ledger.charges[0]
    assert user_id == runtime.user_id
    assert tokens > 0
    assert isinstance(cost, Decimal)


async def test_the_charge_is_the_number_the_stream_reported(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(ADD_PROMPT)

    usage = [c for c in outcome.chunks if c["type"] == "data-turn-usage"]

    _user, tokens, cost = runtime.ledger.charges[0]
    assert usage[0]["data"]["totalTokens"] == tokens
    assert usage[0]["data"]["costUsd"] == str(cost)
    assert usage[0]["transient"] is True


async def test_a_turn_that_calls_a_tool_costs_more_than_one_that_does_not(
    runtime: SyntheticRuntime,
    other_runtime: SyntheticRuntime,
) -> None:
    await runtime.run(PLAIN_PROMPT)
    await other_runtime.run(ADD_PROMPT)

    assert other_runtime.ledger.total_tokens > runtime.ledger.total_tokens


async def test_every_turn_is_charged_what_that_turn_reported(
    runtime: SyntheticRuntime,
) -> None:
    plain = await runtime.run(PLAIN_PROMPT)
    tooled = await runtime.run(ADD_PROMPT)

    charged = [tokens for _user, tokens, _cost in runtime.ledger.charges]

    assert charged == [_reported_tokens(plain), _reported_tokens(tooled)]
