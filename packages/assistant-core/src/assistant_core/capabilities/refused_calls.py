"""A call a tool refuses, marked ``corrected`` so a reader tells it from a failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities.abstract import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.exceptions import ToolFailed, ToolFailedError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

from assistant_core.graph.tool_summary import summary_chunks


class CallRefused(ToolFailed):
    """The tool refuses the call as the model sent it, and nothing failed."""


@dataclass
class MarkRefusedCalls[AgentDepsT](AbstractCapability[AgentDepsT]):
    """Carry a ``corrected`` summary on the result of every call a tool refuses."""

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        del ctx, tool_def
        try:
            return await handler(args)
        except ToolFailedError as failed:
            match failed.__cause__:
                case CallRefused(message=said):
                    failed.tool_failed.metadata = summary_chunks(
                        call.tool_call_id, said, status="corrected"
                    )
            raise
