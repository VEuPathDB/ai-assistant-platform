from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.messages import (
    CapabilityLoadDeltaEvent,
    CapabilityLoadDeltaPart,
    ModelSettingsDeltaEvent,
    ModelSettingsDeltaPart,
    ToolAvailabilityDeltaEvent,
    ToolAvailabilityDeltaPart,
)

from assistant_core.conversation.vercel_adapter import PhaseStreamEmitter


async def _events(*events: Any) -> AsyncIterator[Any]:
    for event in events:
        yield event


async def _data_types(event: Any) -> list[str]:
    emitter = PhaseStreamEmitter(message_id="m1")
    return [
        chunk.type
        async for chunk in emitter.chunks(_events(event))
        if chunk.type.startswith("data-")
    ]


@pytest.mark.parametrize(
    "event",
    [
        ModelSettingsDeltaEvent(
            part=ModelSettingsDeltaPart(settings={"thinking": "medium"}, top_level=True)
        ),
        ToolAvailabilityDeltaEvent(part=ToolAvailabilityDeltaPart()),
        CapabilityLoadDeltaEvent(part=CapabilityLoadDeltaPart(loaded=["search"])),
    ],
)
async def test_a_delta_the_runtime_keeps_in_its_history_is_not_streamed(
    event: Any,
) -> None:
    assert await _data_types(event) == []
