"""The bound a turn puts on a checkpoint call."""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Sequence
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from assistant_core.conversation.checkpointer import BoundedCheckpointCalls
from assistant_core.conversation.deadline import CheckpointTimeoutError
from assistant_core.platform.config import RuntimeSettings, use_settings_source


class _NeverAnswers(BaseCheckpointSaver[str]):
    """A checkpointer whose every call hangs, as a dead connection does."""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        await asyncio.Event().wait()
        return None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        await asyncio.Event().wait()
        return config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.Event().wait()


class _Answers(BaseCheckpointSaver[str]):
    """A checkpointer that answers at once."""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return config

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return None


class _BoundedHang(BoundedCheckpointCalls, _NeverAnswers):
    """The bound composed over a checkpointer that never answers."""


class _BoundedAnswer(BoundedCheckpointCalls, _Answers):
    """The bound composed over a checkpointer that answers."""


_CONFIG: RunnableConfig = {"configurable": {"thread_id": "t-1"}}


@pytest.fixture
def short_deadline() -> Generator[None]:
    use_settings_source(lambda: RuntimeSettings(checkpoint_timeout_seconds=0.05))
    yield
    use_settings_source(RuntimeSettings)


async def test_a_read_that_never_resolves_fails_inside_the_window(
    short_deadline: None,
) -> None:
    """A checkpoint read that never answers ends the deadline, not the turn."""
    del short_deadline
    saver = _BoundedHang()
    started = asyncio.get_running_loop().time()

    with pytest.raises(CheckpointTimeoutError) as caught:
        await saver.aget_tuple(_CONFIG)

    assert caught.value.operation == "get"
    assert caught.value.seconds == 0.05
    assert asyncio.get_running_loop().time() - started < 1.0


async def test_a_write_that_never_resolves_becomes_a_typed_failure(
    short_deadline: None,
) -> None:
    """A checkpoint write that never answers names itself."""
    del short_deadline
    saver = _BoundedHang()

    with pytest.raises(CheckpointTimeoutError) as caught:
        await saver.aput(_CONFIG, Checkpoint(), CheckpointMetadata(), {})

    assert caught.value.operation == "put"
    assert "put" in str(caught.value)


async def test_a_write_of_task_output_that_never_resolves_fails(
    short_deadline: None,
) -> None:
    """The writes of a task carry the same bound as the checkpoint."""
    del short_deadline
    saver = _BoundedHang()

    with pytest.raises(CheckpointTimeoutError) as caught:
        await saver.aput_writes(_CONFIG, [("channel", 1)], "task-1")

    assert caught.value.operation == "put writes"


async def test_a_saver_that_answers_passes_through(short_deadline: None) -> None:
    """The bound adds nothing to a checkpointer that answers."""
    del short_deadline
    saver = _BoundedAnswer()

    assert await saver.aget_tuple(_CONFIG) is None
    assert await saver.aput(_CONFIG, Checkpoint(), CheckpointMetadata(), {}) == _CONFIG
    assert await saver.aput_writes(_CONFIG, [("channel", 1)], "task-1") is None


async def test_the_window_comes_from_the_settings() -> None:
    """The bound reads the configured number of seconds."""
    use_settings_source(lambda: RuntimeSettings(checkpoint_timeout_seconds=0.01))
    try:
        with pytest.raises(CheckpointTimeoutError) as caught:
            await _BoundedHang().aget_tuple(_CONFIG)
    finally:
        use_settings_source(RuntimeSettings)

    assert caught.value.seconds == 0.01
