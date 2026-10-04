"""A run's instruction sections held to the text the run first read, and each
section a tool call changed sent after that call's result, so every request of a
run extends the one before it."""

from __future__ import annotations

import dataclasses
import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import AbstractCapability, WrapRunHandler
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    SystemPromptPart,
    ToolCallPart,
    ToolReturn,
    UserContent,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import ToolDefinition

type SectionRender[DepsT] = Callable[
    [RunContext[DepsT]], str | Awaitable[str | None] | None
]
type Section[DepsT] = Callable[[RunContext[DepsT]], Awaitable[str | None]]

SECTION_UPDATE_LEAD = (
    "Briefing update, not a message from the user. The call above changed these "
    "sections of your instructions; each one below replaces the section of the "
    "same heading."
)
_SECTION_SEPARATOR = "\n\n---\n\n"
# A note names the run that sent it in ``dynamic_ref``, which pydantic-ai acts on
# only when a dynamic system prompt function of that name exists.
_NOTE_REF = "section-update:"

_HEADING = re.compile(r"^(#+) ")
# A heading's trailing parenthesis carries counts, so it names no other section.
_HEADING_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")
_GONE = re.compile(r"^The section (?P<heading>.+) no longer applies\.$")


def section_update(sections: Sequence[str]) -> str:
    """The text that sends ``sections``, each replacing its namesake."""
    return f"{SECTION_UPDATE_LEAD}\n\n{_SECTION_SEPARATOR.join(sections)}"


def _texts(part: UserPromptPart | SystemPromptPart) -> list[str]:
    content = part.content
    items = [content] if isinstance(content, str) else list(content)
    return [item for item in items if isinstance(item, str)]


def _update_text(part: UserPromptPart | SystemPromptPart) -> str | None:
    return next(
        (text for text in _texts(part) if text.startswith(SECTION_UPDATE_LEAD)), None
    )


def is_section_update(part: UserPromptPart | SystemPromptPart) -> bool:
    """Whether a part carries section updates rather than the user's words."""
    return _update_text(part) is not None


def _update_items(part: UserPromptPart | SystemPromptPart) -> list[str]:
    """The sections a part sends after the update lead, in order."""
    text = _update_text(part)
    if text is None:
        return []
    return text.removeprefix(SECTION_UPDATE_LEAD).lstrip("\n").split(_SECTION_SEPARATOR)


def _section_key(line: str) -> str:
    return _HEADING_SUFFIX.sub("", line).strip()


def _replaced(briefing: str, heading: str, text: str | None) -> str:
    """The briefing with the section under ``heading`` replaced by ``text``.

    A section runs to the next heading of its level or higher. A heading the
    briefing does not hold adds ``text`` at its end.
    """
    match = _HEADING.match(heading)
    lines = briefing.split("\n")
    key = _section_key(heading)
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if _HEADING.match(line) and _section_key(line) == key
        ),
        None,
    )
    if start is None or match is None:
        return briefing if text is None else f"{briefing}\n\n{text}"
    level = len(match.group(1))
    end = next(
        (
            j
            for j in range(start + 1, len(lines))
            if (found := _HEADING.match(lines[j])) and len(found.group(1)) <= level
        ),
        len(lines),
    )
    kept = [
        *lines[:start],
        *([] if text is None else [*text.split("\n"), ""]),
        *lines[end:],
    ]
    return "\n".join(kept).strip("\n")


def briefing_now(instructions: str, messages: Sequence[ModelMessage]) -> str:
    """The instructions as the model reads them after every section update in
    ``messages``: each updated section in its place, in its latest text."""
    briefing = instructions
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if not isinstance(part, UserPromptPart | SystemPromptPart):
                continue
            for item in _update_items(part):
                gone = _GONE.match(item)
                if gone is not None:
                    briefing = _replaced(briefing, gone.group("heading"), None)
                else:
                    briefing = _replaced(briefing, item.split("\n", 1)[0], item)
    return briefing


async def _rendered[DepsT](
    render: SectionRender[DepsT], ctx: RunContext[DepsT]
) -> str | None:
    text = render(ctx)
    return await text if inspect.isawaitable(text) else text


def _heading(text: str) -> str:
    """The first line of a section, which names it."""
    return text.split("\n", 1)[0]


def _sent_after(content: str | Sequence[UserContent] | None) -> list[UserContent]:
    """The content a tool already sends after its result, as a list."""
    match content:
        case None:
            return []
        case str() as text:
            return [text]
        case _:
            return list(content)


def _with_update(result: Any, update: str) -> Any:
    """The tool's result with ``update`` sent to the model after it."""
    match result:
        case ToolReturn():
            return ToolReturn(
                return_value=result.return_value,
                content=[*_sent_after(result.content), update],
                metadata=result.metadata,
            )
        case _:
            return ToolReturn(return_value=result, content=update)


@dataclass
class _RunSections:
    """What one run read of each section first, and the latest text it was sent."""

    held: dict[str, str | None] = field(default_factory=dict)
    latest: dict[str, str | None] = field(default_factory=dict)


@dataclass
class StableInstructions[DepsT](AbstractCapability[DepsT]):
    """Holds each section a run reads to the text the run first read.

    Register a section with ``agent.instructions(stable.section(render))`` and
    add this capability to the agent. Outside a run a section renders as it
    stands. An update follows the tool result as a system note, in history and on
    the wire.
    """

    _renders: dict[str, SectionRender[DepsT]] = field(default_factory=dict)
    _runs: dict[str, _RunSections] = field(default_factory=dict)

    def section(self, render: SectionRender[DepsT]) -> Section[DepsT]:
        """The instruction a run reads in place of ``render``."""
        key = render.__qualname__
        self._renders[key] = render

        async def read(ctx: RunContext[DepsT]) -> str | None:
            run = self._runs.get(ctx.run_id or "")
            if run is None:
                return await _rendered(render, ctx)
            if key not in run.held:
                run.held[key] = run.latest[key] = await _rendered(render, ctx)
            return run.held[key]

        read.__name__ = render.__name__
        read.__qualname__ = render.__qualname__
        return read

    async def wrap_run(
        self,
        ctx: RunContext[DepsT],
        *,
        handler: WrapRunHandler,
    ) -> AgentRunResult[Any]:
        run_id = ctx.run_id or ""
        self._runs[run_id] = _RunSections()
        try:
            return await handler()
        finally:
            self._runs.pop(run_id, None)

    async def after_tool_execute(
        self,
        ctx: RunContext[DepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        del call, tool_def, args
        run = self._runs.get(ctx.run_id or "")
        if run is None:
            return result
        changed: list[str] = []
        for key, before in list(run.latest.items()):
            now = await _rendered(self._renders[key], ctx)
            if now == before:
                continue
            run.latest[key] = now
            if now is not None:
                changed.append(now)
            elif before is not None:
                changed.append(f"The section {_heading(before)} no longer applies.")
        if not changed:
            return result
        return _with_update(result, section_update(changed))

    async def before_model_request(
        self,
        ctx: RunContext[DepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        """Send each update of this run as a system note, the same way on every
        request, and drop the notes of earlier runs: this run's instructions
        already hold every section as it stands."""
        tag = f"{_NOTE_REF}{ctx.run_id}"
        return replace(
            request_context,
            messages=[_as_system_notes(m, tag) for m in request_context.messages],
        )


def _as_system_notes(message: ModelMessage, tag: str) -> ModelMessage:
    """The message with this run's section updates in the system voice and no
    section update of another run."""
    if not isinstance(message, ModelRequest):
        return message
    parts: list[ModelRequestPart] = []
    for part in message.parts:
        match part:
            case SystemPromptPart() if is_section_update(part):
                if part.dynamic_ref == tag:
                    parts.append(part)
            case UserPromptPart() if (update := _update_text(part)) is not None:
                own = [item for item in _sent_after(part.content) if item != update]
                if own:
                    parts.append(dataclasses.replace(part, content=own))
                parts.append(
                    SystemPromptPart(
                        content=update, timestamp=part.timestamp, dynamic_ref=tag
                    )
                )
            case _:
                parts.append(part)
    return dataclasses.replace(message, parts=parts)


__all__ = [
    "SECTION_UPDATE_LEAD",
    "Section",
    "SectionRender",
    "StableInstructions",
    "briefing_now",
    "is_section_update",
    "section_update",
]
