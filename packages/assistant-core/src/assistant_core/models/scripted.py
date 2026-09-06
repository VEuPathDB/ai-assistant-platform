"""A deterministic scripted model for tests.

One ``FunctionModel`` serves several agents. Which agent it is serving is read
from the tool names the agent offers; that role's script then picks the next
tool call, or the answer text, from the messages so far. The scripts are the
product's; this module is the machinery that runs them.

Two context vars carry what the runner knew before it started a run, so a
script can branch on the scope and on the user's latest message without
digging them out of the history.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

UNKNOWN_ROLE = "unknown"
TERMINAL_TOOL = "final_result"

current_scope_id: ContextVar[str] = ContextVar("scripted_scope_id", default="")
current_user_text: ContextVar[str] = ContextVar("scripted_user_text", default="")

# An agent whose output is a tool answers with a call; one whose output is
# prose answers with text.
ScriptedPart = ToolCallPart | TextPart
RoleScript = Callable[[list[ModelMessage]], ScriptedPart]


@dataclass(frozen=True)
class RoleMarkers:
    """Tool names that identify one role. The first entry whose markers
    intersect the agent's tool names wins, so order is the tie-breaker."""

    role: str
    markers: frozenset[str]


def tool_names(info: AgentInfo) -> frozenset[str]:
    return frozenset(t.name for t in info.function_tools)


def detect_role(info: AgentInfo, roles: Sequence[RoleMarkers]) -> str:
    names = tool_names(info)
    for entry in roles:
        if entry.markers & names:
            return entry.role
    return UNKNOWN_ROLE


def user_texts(messages: list[ModelMessage]) -> list[str]:
    """Every user message the run carries, in order."""
    return [
        part.content
        for msg in messages
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]


def last_user_text(messages: list[ModelMessage]) -> str:
    texts = user_texts(messages)
    return texts[-1] if texts else ""


def joined_user_text(messages: list[ModelMessage]) -> str:
    """All user-prompt text across the run, joined. An attached file rides as
    its own text part, so a block can land in a different part from the typed
    message. Scan them all."""
    return "\n".join(user_texts(messages))


def current_turn(messages: list[ModelMessage]) -> list[ModelMessage]:
    """The messages of the turn in progress.

    A thread's earlier turns ride in the run's history, so a script that asks
    what THIS turn did reads it here rather than from the whole run.
    """
    start = 0
    for index, msg in enumerate(messages):
        if isinstance(msg, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in msg.parts
        ):
            start = index
    return messages[start:]


def called_tool_parts(messages: list[ModelMessage]) -> list[ToolCallPart]:
    return [
        part
        for msg in messages
        if isinstance(msg, ModelResponse)
        for part in msg.parts
        if isinstance(part, ToolCallPart)
    ]


def _called_tools(messages: list[ModelMessage]) -> list[str]:
    return [p.tool_name for p in called_tool_parts(messages)]


def tool_return_parts(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for msg in messages
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, ToolReturnPart)
    ]


def retry_prompt_parts(messages: list[ModelMessage]) -> list[RetryPromptPart]:
    """The refusals a tool sent back, so a script can branch on one."""
    return [
        part
        for msg in messages
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, RetryPromptPart)
    ]


def has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def scripted_call(name: str, args: dict[str, Any]) -> ToolCallPart:
    return ToolCallPart(
        tool_name=name,
        args=args,
        tool_call_id=f"mock_{name}_{uuid4().hex[:10]}",
    )


def scripted_text(text: str) -> TextPart:
    return TextPart(content=text)


def next_unmade_call(
    sequence: list[ToolCallPart],
    messages: list[ModelMessage],
) -> ToolCallPart:
    """The first step of ``sequence`` the run has not made yet.

    The terminal step always wins once it is reached, so a sequence never
    replays a call that already produced its result.
    """
    called = _called_tools(messages)
    for step in sequence:
        if step.tool_name == TERMINAL_TOOL:
            return step
        if step.tool_name not in called:
            return step
    return sequence[-1]


def deferred_tool_resolved(messages: list[ModelMessage], tool_name: str) -> bool:
    """True only for the FRESH resume: ``tool_name`` came back with a result
    and no later user message has superseded it."""
    resolved = False
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        parts = msg.parts
        has_tool_return = any(isinstance(p, ToolReturnPart) for p in parts)
        if any(
            isinstance(p, ToolReturnPart) and p.tool_name == tool_name for p in parts
        ):
            resolved = True
        elif not has_tool_return and any(isinstance(p, UserPromptPart) for p in parts):
            resolved = False
    return resolved


def terminal_call(args: dict[str, Any]) -> ToolCallPart:
    return scripted_call(TERMINAL_TOOL, args)


@dataclass(frozen=True)
class ScriptedModel:
    """A ``FunctionModel`` that answers from one script per role."""

    roles: tuple[RoleMarkers, ...]
    scripts: Mapping[str, RoleScript]
    unknown: RoleScript
    model_name: str = "mock:deterministic"

    def response_part(
        self,
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ScriptedPart:
        role = detect_role(info, self.roles)
        script = self.scripts.get(role, self.unknown)
        return script(messages)

    def as_function_model(self) -> FunctionModel:
        def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[self.response_part(messages, info)])

        async def _stream(
            messages: list[ModelMessage],
            info: AgentInfo,
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            part = self.response_part(messages, info)
            if isinstance(part, TextPart):
                yield part.content
                return
            yield {
                0: DeltaToolCall(
                    name=part.tool_name,
                    json_args=part.args_as_json_str(),
                    tool_call_id=part.tool_call_id,
                ),
            }

        return FunctionModel(
            _respond,
            stream_function=_stream,
            model_name=self.model_name,
        )
