"""A host starts only a task declared for a host to start."""

from __future__ import annotations

from uuid import uuid4

import pytest

from assistant_core.tasks.declaration import declare_durable_tool, empty_durable_tools
from assistant_core.tasks.host_task import (
    ModelStartedDurableToolError,
    ThreadLockedHostTaskError,
    start_host_task,
)


async def test_a_host_cannot_start_a_task_a_model_starts() -> None:
    with empty_durable_tools():
        tool = declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)

        with pytest.raises(ModelStartedDurableToolError) as caught:
            await start_host_task(
                tool,
                conversation_id=uuid4(),
                user_id=uuid4(),
                kwargs={},
                lock="crunch:1",
            )

    assert str(caught.value) == (
        "durable tool 'crunch' is started by an agent tool: declare it with "
        "host_started=True to start it with start_host_task()"
    )


async def test_a_host_task_never_takes_the_threads_lock() -> None:
    thread = uuid4()
    with empty_durable_tools():
        tool = declare_durable_tool(
            tool_name="install_upload",
            estimated_duration_seconds=600,
            host_started=True,
        )

        with pytest.raises(ThreadLockedHostTaskError) as caught:
            await start_host_task(
                tool,
                conversation_id=thread,
                user_id=uuid4(),
                kwargs={},
                lock=str(thread),
            )

    assert str(caught.value) == (
        "host-started task 'install_upload' names the thread's id as its lock: "
        "a chat turn of the thread would wait behind it"
    )
