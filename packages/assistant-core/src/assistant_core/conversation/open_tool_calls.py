"""The tool calls a turn opened and never closed."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ConfigDict
from pydantic_ai.ui.vercel_ai.response_types import ToolOutputErrorChunk
from sqlalchemy import select

from assistant_core.conversation.event_writer import ChatWriter
from assistant_core.persistence.models import ConversationEvent
from assistant_core.platform.db import async_session_factory
from assistant_core.platform.pydantic_base import CamelModel

_OPENING = frozenset({"tool-input-start", "tool-input-available"})
_CLOSING = frozenset(
    {
        "tool-output-available",
        "tool-output-error",
        "tool-output-denied",
        "tool-approval-request",
    },
)


class _ToolLifecycleChunk(CamelModel):
    """The two fields a tool call's state is read from."""

    model_config = ConfigDict(extra="ignore")

    type: str = ""
    tool_call_id: str = ""


class OpenToolCalls:
    """The calls a stream has opened and not closed, in the order they opened.

    A driver keeps one of these instead of the chunks themselves, so a turn of
    any length costs one entry per call.
    """

    def __init__(self) -> None:
        self._state: dict[str, bool] = {}

    def observe(self, chunk: dict[str, Any]) -> None:
        parsed = _ToolLifecycleChunk.model_validate(chunk)
        if not parsed.tool_call_id:
            return
        if parsed.type in _OPENING:
            self._state[parsed.tool_call_id] = True
        elif parsed.type in _CLOSING:
            self._state[parsed.tool_call_id] = False

    def ids(self) -> list[str]:
        return [call_id for call_id, is_open in self._state.items() if is_open]


def open_tool_call_ids(chunks: Iterable[dict[str, Any]]) -> list[str]:
    """The calls in this chunk sequence that carry an input and no result."""
    calls = OpenToolCalls()
    for chunk in chunks:
        calls.observe(chunk)
    return calls.ids()


async def write_tool_call_errors(
    writer: ChatWriter,
    tool_call_ids: Sequence[str],
    error_text: str,
) -> None:
    """End the named calls, so a client renders no running call in a dead turn."""
    for tool_call_id in tool_call_ids:
        await writer.write(
            ToolOutputErrorChunk(
                tool_call_id=tool_call_id,
                error_text=error_text,
            ).model_dump(by_alias=True, mode="json", exclude_none=True),
        )


async def close_open_tool_calls(writer: ChatWriter, error_text: str) -> None:
    """End every call the turn's log left running, reading the log itself."""
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ConversationEvent.chunk)
            .where(
                ConversationEvent.conversation_id == writer.conversation_id,
                ConversationEvent.turn_id == writer.turn_id,
                ConversationEvent.task_id.is_(None),
            )
            .order_by(ConversationEvent.id),
        )
    await write_tool_call_errors(writer, open_tool_call_ids(rows.all()), error_text)
