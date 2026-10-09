from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior

from assistant_core.conversation.vercel_adapter import PhaseStreamEmitter
from assistant_core.errors import ModelDeclinedError

_WORDED = "Claude Sonnet 5.5 declined this request. Try rephrasing it."


async def _raising(error: Exception) -> AsyncIterator[Any]:
    for _ in ():
        yield None
    raise error


async def _chunks(
    emitter: PhaseStreamEmitter, error: Exception
) -> list[dict[str, Any]]:
    return [
        chunk.model_dump(by_alias=True, mode="json", exclude_none=True)
        async for chunk in emitter.chunks(_raising(error))
        if chunk.type in {"error", "data-turn-withdrawn"}
    ]


async def test_a_worded_decline_reaches_the_reader_in_the_host_s_words() -> None:
    emitter = PhaseStreamEmitter(message_id="m1", prompt_message_id="u1")

    chunks = await _chunks(emitter, ModelDeclinedError(_WORDED, model_id="a:b"))

    assert chunks == [
        {
            "type": "data-turn-withdrawn",
            "data": {"errorText": _WORDED, "messageId": "u1"},
        },
        {"type": "error", "errorText": _WORDED},
    ]


async def test_a_turn_that_resumed_a_parked_call_withdraws_its_run_alone() -> None:
    emitter = PhaseStreamEmitter(message_id="m1")

    chunks = await _chunks(emitter, ModelDeclinedError(_WORDED))

    assert chunks == [
        {"type": "data-turn-withdrawn", "data": {"errorText": _WORDED}},
        {"type": "error", "errorText": _WORDED},
    ]


@pytest.mark.parametrize("error", [UnexpectedModelBehavior("bad"), RuntimeError("x")])
async def test_any_other_failure_withdraws_nothing(error: Exception) -> None:
    emitter = PhaseStreamEmitter(message_id="m1", prompt_message_id="u1")

    chunks = await _chunks(emitter, error)

    assert [chunk["type"] for chunk in chunks] == ["error"]
