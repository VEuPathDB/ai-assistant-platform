"""The memory store's turn deadline."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest

from assistant_core.memory.deadline import (
    MemoryStoreTimeoutError,
    memory_store_deadline,
)
from assistant_core.platform.config import RuntimeSettings, use_settings_source


@pytest.fixture
def short_deadline() -> Generator[None]:
    use_settings_source(lambda: RuntimeSettings(memory_store_timeout_seconds=0.05))
    yield
    use_settings_source(RuntimeSettings)


async def test_a_call_that_never_resolves_becomes_a_typed_failure(
    short_deadline: None,
) -> None:
    """A store call that never answers ends the deadline, not the turn."""
    del short_deadline
    with pytest.raises(MemoryStoreTimeoutError) as caught:
        async with memory_store_deadline("retrieval"):
            await asyncio.Event().wait()

    assert caught.value.operation == "retrieval"
    assert caught.value.seconds == 0.05
    assert "retrieval" in str(caught.value)


async def test_a_call_that_answers_in_time_passes_through(
    short_deadline: None,
) -> None:
    """The deadline adds nothing to a call that answers."""
    del short_deadline
    answered = False
    async with memory_store_deadline("retrieval"):
        answered = True

    assert answered is True


async def test_the_deadline_does_not_claim_a_timeout_it_did_not_cause(
    short_deadline: None,
) -> None:
    """An inner ``TimeoutError`` reaches the caller unchanged."""
    del short_deadline
    with pytest.raises(TimeoutError) as caught:
        async with memory_store_deadline("auto-write"):
            raise TimeoutError(4)

    assert not isinstance(caught.value, MemoryStoreTimeoutError)


async def test_the_window_comes_from_the_settings() -> None:
    """The deadline reads the configured number of seconds."""
    use_settings_source(lambda: RuntimeSettings(memory_store_timeout_seconds=0.01))
    try:
        with pytest.raises(MemoryStoreTimeoutError) as caught:
            async with memory_store_deadline("auto-write"):
                await asyncio.Event().wait()
    finally:
        use_settings_source(RuntimeSettings)

    assert caught.value.seconds == 0.01
