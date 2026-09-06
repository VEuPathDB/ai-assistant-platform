"""Anti-thrash circuit breaker for a run that repeats one read-only call.

After a tool result an agent can fall into a tight loop reading the same
read-only tool. ``request_limit`` eventually catches this, but by then
hundreds of tokens are burned. The guard refuses the Nth consecutive identical
call, and ends the run if the model makes it again.

The tool names are the product's, so the guard is constructed with them; a
guard built with no vocabulary never blocks. :class:`RepetitionGuard` is the
capability that runs the check at call time, on whichever guard the turn was
built with.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities.abstract import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

DEFAULT_REPETITION_THRESHOLD: int = 3

# Every refusal opens with this phrase, so a reader of a captured run can tell
# a guard refusal from a tool's own failure.
REPETITION_MARKER: str = "identical arguments"


def _args_fingerprint(args: object) -> str:
    serialized = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class RepetitionBlock:
    """One refused call: which tool, how many times, and whether the run ends."""

    tool_name: str
    count: int
    escalated: bool

    @property
    def message(self) -> str:
        opening = (
            f"You have called {self.tool_name} {self.count} times with "
            f"{REPETITION_MARKER} and no intervening state change."
        )
        if self.escalated:
            return (
                f"{opening} You were already asked to change approach and "
                f"repeated the call. The run stops here."
            )
        return (
            f"{opening} This is a loop. Change approach: take a different "
            f"action, call a tool that changes state, or produce your final "
            f"answer. Do NOT call {self.tool_name} again with these arguments."
        )


@dataclass
class ToolRepetitionGuard:
    """Tracks consecutive identical read-only tool calls and blocks loops."""

    read_only_tools: frozenset[str] = frozenset()
    threshold: int = DEFAULT_REPETITION_THRESHOLD
    _last_tool: str = field(default="", init=False, repr=False)
    _last_fingerprint: str = field(default="", init=False, repr=False)
    _consecutive_count: int = field(default=0, init=False, repr=False)
    _total_blocked: int = field(default=0, init=False, repr=False)
    _stopped_call_id: str = field(default="", init=False, repr=False)

    @property
    def total_blocked(self) -> int:
        return self._total_blocked

    @property
    def stopped_call_id(self) -> str:
        """The call whose refusal ends the run, empty while the run may go on.

        The driver stops once this call's result has reached the client, so a
        sibling in the same batch still reports its own outcome.
        """
        return self._stopped_call_id

    def _reset(self) -> None:
        self._last_tool = ""
        self._last_fingerprint = ""
        self._consecutive_count = 0

    def check(
        self,
        tool_name: str,
        tool_args: object,
        *,
        tool_call_id: str = "",
    ) -> RepetitionBlock | None:
        """Return ``None`` to proceed, or the block that refuses the call.

        A tool outside the vocabulary is progress, so it clears the streak.
        """
        if tool_name not in self.read_only_tools:
            self._reset()
            return None

        fingerprint = _args_fingerprint(tool_args)
        if tool_name == self._last_tool and fingerprint == self._last_fingerprint:
            self._consecutive_count += 1
        else:
            self._last_tool = tool_name
            self._last_fingerprint = fingerprint
            self._consecutive_count = 1

        if self._consecutive_count < self.threshold:
            return None
        self._total_blocked += 1
        escalated = self._consecutive_count > self.threshold
        if escalated and not self._stopped_call_id:
            self._stopped_call_id = tool_call_id
        return RepetitionBlock(
            tool_name=tool_name,
            count=self._consecutive_count,
            escalated=escalated,
        )


@dataclass
class RepetitionGuard(AbstractCapability[object]):
    """Runs the repetition check before every tool the agent calls.

    A block returns the refusal as the tool's result, never as ``ModelRetry``:
    a retry raised here shares the tool's retry budget, so a tool that already
    retried once would abort the whole run on the guard's first nudge. A first
    block is a result the model can route around; a second block on the same
    call ends the run via ``guard.stopped_call_id``.
    """

    guard: ToolRepetitionGuard = field(default_factory=ToolRepetitionGuard)

    async def wrap_tool_execute(
        self,
        ctx: RunContext[object],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        del ctx, tool_def
        block = self.guard.check(call.tool_name, args, tool_call_id=call.tool_call_id)
        if block is None:
            return await handler(args)
        return block.message


__all__ = [
    "DEFAULT_REPETITION_THRESHOLD",
    "REPETITION_MARKER",
    "RepetitionBlock",
    "RepetitionGuard",
    "ToolRepetitionGuard",
]
