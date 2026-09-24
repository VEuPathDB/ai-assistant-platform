"""Starting a durable task that no model call started.

The host names the lock, so a long task never queues the thread's turns
behind it. The row answers no call, so the thread never hears of it.
"""

from __future__ import annotations

from uuid import UUID

from assistant_core.platform.types import JSONObject
from assistant_core.tasks.declaration import DurableTool, require_declared
from assistant_core.tasks.service import create_background_task, defer_durable_job


class ModelStartedDurableToolError(ValueError):
    """A host starts a declaration only an agent tool starts."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"durable tool {tool_name!r} is started by an agent tool: declare it "
            "with host_started=True to start it with start_host_task()",
        )
        self.tool_name = tool_name


class ThreadLockedHostTaskError(ValueError):
    """A host names the thread's id as a host-started task's lock."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"host-started task {tool_name!r} names the thread's id as its lock: "
            "a chat turn of the thread would wait behind it",
        )
        self.tool_name = tool_name


async def start_host_task(
    tool: DurableTool,
    *,
    conversation_id: UUID,
    user_id: UUID,
    kwargs: JSONObject,
    lock: str,
) -> UUID:
    """Write a host-started task's row, defer its job under ``lock``, return its id.

    The body receives ``kwargs`` as its keyword arguments.
    """
    if not require_declared(tool).host_started:
        raise ModelStartedDurableToolError(tool.tool_name)
    if lock == str(conversation_id):
        raise ThreadLockedHostTaskError(tool.tool_name)
    args: JSONObject = {"args": [], "kwargs": kwargs}
    task_id = await create_background_task(
        conversation_id=conversation_id,
        user_id=user_id,
        tool_name=tool.tool_name,
        args=args,
        tool_call_id=None,
        estimated_duration_seconds=tool.estimated_duration_seconds,
    )
    await defer_durable_job(
        tool,
        task_id=task_id,
        thread_id=conversation_id,
        args=args,
        lock=lock,
    )
    return task_id


__all__ = [
    "ModelStartedDurableToolError",
    "ThreadLockedHostTaskError",
    "start_host_task",
]
