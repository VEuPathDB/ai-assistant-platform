"""The scratchpad toolset a host attaches to any agent it wants to take notes."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturn,
)
from pydantic_ai.tools import RunContext, Tool, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.toolsets.prepared import PreparedToolset

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.scratchpad.notebook import ScratchpadNotebook
from assistant_core.scratchpad.rendering import ScratchpadGuidance
from assistant_core.scratchpad.tools import (
    ScratchpadUnavailable,
    delete_note,
    list_notes,
    note,
    pin_note,
    promote_note,
    read_note,
    search_notes,
    unpin_note,
    update_note,
)

# Nothing but ``note`` can act on an empty scratchpad.
_EMPTY_SCRATCHPAD_HIDDEN = frozenset(
    {
        "list_notes",
        "search_notes",
        "read_note",
        "update_note",
        "delete_note",
        "pin_note",
        "unpin_note",
        "promote_to_memory",
    }
)

_READ_TOOLS = frozenset({"search_notes", "list_notes", "read_note"})

_MAX_CONSECUTIVE_READ = 2

_NO_GUIDANCE = ScratchpadGuidance()


def _read_tools_to_hide(messages: Sequence[ModelMessage]) -> frozenset[str]:
    """The read tools that disappear this step, because they just ran twice.

    Hiding one makes the agent take a different action before it reads again.
    Only the tail of the history counts: any other tool call ends the streak.
    """
    counts: dict[str, int] = {}
    for message in reversed(messages):
        if not isinstance(message, ModelResponse):
            continue
        for part in reversed(message.parts):
            if not isinstance(part, ToolCallPart):
                continue
            if part.tool_name not in _READ_TOOLS:
                return _over_the_streak(counts)
            counts[part.tool_name] = counts.get(part.tool_name, 0) + 1
    return _over_the_streak(counts)


def _over_the_streak(counts: dict[str, int]) -> frozenset[str]:
    return frozenset(
        {name for name, seen in counts.items() if seen >= _MAX_CONSECUTIVE_READ}
    )


async def _prepare_scratchpad_tools(
    ctx: RunContext[AssistantDeps],
    tool_defs: list[ToolDefinition],
) -> list[ToolDefinition]:
    factory = ctx.deps.db_session_factory
    conversation_id = ctx.deps.conversation_id
    if factory is None or conversation_id is None:
        return tool_defs
    total = await ScratchpadNotebook(factory, conversation_id).total_notes()
    if total == 0:
        return [td for td in tool_defs if td.name not in _EMPTY_SCRATCHPAD_HIDDEN]
    hidden = _read_tools_to_hide(ctx.messages)
    return [td for td in tool_defs if td.name not in hidden]


def _promote_tool(sentence: str, kind: str) -> Tool[AssistantDeps]:
    """The promote tool, under the kind and the sentence the host named."""

    async def promote_to_memory(
        ctx: RunContext[AssistantDeps],
        note_id: str,
    ) -> ToolReturn[str | ScratchpadUnavailable]:
        """Promote a scratchpad note to the user's long-term memory.

        Use when a note holds something worth remembering after this
        conversation ends. The note's ``title`` / ``summary`` / ``body`` map
        one to one onto the memory's ``name`` / ``summary`` /
        ``content.body``. The note stays where it is; a new cross-thread
        memory is created.
        """
        return await promote_note(ctx, note_id, kind=kind)

    tool = Tool[AssistantDeps](promote_to_memory)
    if sentence:
        tool.description = f"{tool.description}\n\n{sentence}"
    return tool


def build_scratchpad_toolset(
    *,
    promoted_kind: str,
    guidance: ScratchpadGuidance = _NO_GUIDANCE,
) -> AbstractToolset[AssistantDeps]:
    """The nine scratchpad tools, filtered for what the thread holds now."""
    base = FunctionToolset[AssistantDeps](
        max_retries=3,
        tools=[
            note,
            update_note,
            delete_note,
            pin_note,
            unpin_note,
            list_notes,
            search_notes,
            read_note,
        ],
    )
    base.add_tool(_promote_tool(guidance.promote, promoted_kind))
    return PreparedToolset(wrapped=base, prepare_func=_prepare_scratchpad_tools)
