"""Anti-thrash circuit breaker for a run that reads one tool too often.

After a tool result an agent can fall into a tight loop reading the same
read-only tool. ``request_limit`` eventually catches this, but by then
hundreds of tokens are burned. The guard refuses the Nth consecutive identical
call, and ends the run if the model makes it again in a later request. It also
refuses a call past a tool's per-run cap, whatever the arguments: a run that
retypes its query is a loop the identical-arguments rule never sees.

The tool names are the product's, so the guard is constructed with them; a
guard built with no vocabulary and no caps never blocks.
:class:`RepetitionGuard` is the capability that runs the check at call time,
on whichever guard the turn was built with.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic_ai.capabilities.abstract import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

DEFAULT_REPETITION_THRESHOLD: int = 3

# Each refusal opens with its own phrase, so a reader of a captured run can
# tell the two rules apart, and both from a tool's own failure.
REPETITION_MARKER: str = "identical arguments"
CALL_CAP_MARKER: str = "the call budget"

type BlockRule = Literal["identical_arguments", "call_cap"]


def _args_fingerprint(args: object) -> str:
    serialized = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class RepetitionBlock:
    """One refused call: the tool, the count, the rule, and whether it ends the run."""

    tool_name: str
    count: int
    escalated: bool
    rule: BlockRule

    @property
    def message(self) -> str:
        if self.rule == "call_cap":
            return self._cap_message
        return self._repeat_message

    @property
    def _repeat_message(self) -> str:
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

    @property
    def _cap_message(self) -> str:
        opening = (
            f"You have called {self.tool_name} {self.count} times in this "
            f"run, which is past {CALL_CAP_MARKER} for it."
        )
        if self.escalated:
            return (
                f"{opening} You were already asked to stop calling it and "
                f"called it again. The run stops here."
            )
        return (
            f"{opening} Report what {self.tool_name} has returned so far, and "
            f"stop calling it. A different phrasing reads the same source."
        )


@dataclass
class ToolRepetitionGuard:
    """Blocks a loop on identical arguments and a tool read past its cap.

    ``call_caps`` maps a tool name onto the most calls one run may make to it,
    whatever the arguments. A name the map does not hold is uncapped.
    """

    read_only_tools: frozenset[str] = frozenset()
    call_caps: Mapping[str, int] = field(default_factory=dict)
    threshold: int = DEFAULT_REPETITION_THRESHOLD
    _call_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _last_tool: str = field(default="", init=False, repr=False)
    _last_fingerprint: str = field(default="", init=False, repr=False)
    _consecutive_count: int = field(default=0, init=False, repr=False)
    _total_blocked: int = field(default=0, init=False, repr=False)
    _cap_warned_at: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _repeat_warned_at: int | None = field(default=None, init=False, repr=False)
    _stopped_call_id: str = field(default="", init=False, repr=False)
    _stopped_rule: BlockRule | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        negative = sorted(name for name, cap in self.call_caps.items() if cap < 0)
        if negative:
            msg = f"A call cap cannot be negative: {', '.join(negative)}"
            raise ValueError(msg)

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

    @property
    def stopped_rule(self) -> BlockRule | None:
        """The rule that refused ``stopped_call_id``, None while the run may go on."""
        return self._stopped_rule

    def _reset(self) -> None:
        self._last_tool = ""
        self._last_fingerprint = ""
        self._consecutive_count = 0
        self._repeat_warned_at = None

    def _stop(self, tool_call_id: str, rule: BlockRule) -> None:
        if not self._stopped_call_id:
            self._stopped_call_id = tool_call_id
            self._stopped_rule = rule

    def check(
        self,
        tool_name: str,
        tool_args: object,
        *,
        tool_call_id: str = "",
        run_step: int,
    ) -> RepetitionBlock | None:
        """Return ``None`` to proceed, or the block that refuses the call.

        A tool outside the vocabulary is progress, so it clears the streak. A
        cap is a budget and not a streak: an intervening call never resets it.
        A block ends the run only when ``run_step`` is later than its rule's first
        block, so every call of the warned model response gets the warning.
        """
        capped = self._check_cap(
            tool_name, tool_call_id=tool_call_id, run_step=run_step
        )
        if capped is not None:
            return capped
        if tool_name not in self.read_only_tools:
            self._reset()
            return None

        fingerprint = _args_fingerprint(tool_args)
        if tool_name == self._last_tool and fingerprint == self._last_fingerprint:
            self._consecutive_count += 1
        else:
            self._repeat_warned_at = None
            self._last_tool = tool_name
            self._last_fingerprint = fingerprint
            self._consecutive_count = 1

        if self._consecutive_count < self.threshold:
            return None
        self._total_blocked += 1
        if self._repeat_warned_at is None:
            self._repeat_warned_at = run_step
        escalated = run_step > self._repeat_warned_at
        if escalated:
            self._stop(tool_call_id, "identical_arguments")
        return RepetitionBlock(
            tool_name=tool_name,
            count=self._consecutive_count,
            escalated=escalated,
            rule="identical_arguments",
        )

    def _check_cap(
        self,
        tool_name: str,
        *,
        tool_call_id: str,
        run_step: int,
    ) -> RepetitionBlock | None:
        if tool_name not in self.call_caps:
            return None
        cap = self.call_caps[tool_name]
        count = self._call_counts.get(tool_name, 0) + 1
        self._call_counts[tool_name] = count
        if count <= cap:
            return None
        self._total_blocked += 1
        escalated = run_step > self._cap_warned_at.setdefault(tool_name, run_step)
        if escalated:
            self._stop(tool_call_id, "call_cap")
        return RepetitionBlock(
            tool_name=tool_name,
            count=count,
            escalated=escalated,
            rule="call_cap",
        )


@dataclass
class RepetitionGuard(AbstractCapability[object]):
    """Runs the repetition check before every tool the agent calls.

    A block returns the refusal as the tool's result, never as ``ModelRetry``:
    a retry raised here shares the tool's retry budget, so a tool that already
    retried once would abort the whole run on the guard's first nudge. A first
    block is a result the model can route around; a block in a later model
    request ends the run via ``guard.stopped_call_id``.
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
        del tool_def
        block = self.guard.check(
            call.tool_name,
            args,
            tool_call_id=call.tool_call_id,
            run_step=ctx.run_step,
        )
        if block is None:
            return await handler(args)
        return block.message


__all__ = [
    "CALL_CAP_MARKER",
    "DEFAULT_REPETITION_THRESHOLD",
    "REPETITION_MARKER",
    "BlockRule",
    "RepetitionBlock",
    "RepetitionGuard",
    "ToolRepetitionGuard",
]
