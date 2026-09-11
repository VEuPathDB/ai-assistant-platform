"""The instruments the runtime records, and the readers that fill them.

The instruments are created on the global metrics API, so a process that
configures no meter provider records to a no-op sink and one that configures a
provider exports the same series.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from opentelemetry import metrics
from pydantic import BaseModel, ConfigDict, Field

_turn_meter = metrics.get_meter("assistant.turn")
_sse_meter = metrics.get_meter("assistant.sse")

turn_runs = _turn_meter.create_counter(
    "assistant.turn.runs",
    description="Turns that reached a finish chunk, by finish reason",
    unit="{turn}",
)

turn_duration_s = _turn_meter.create_histogram(
    "assistant.turn.duration",
    description="Wall-clock time from a turn's start chunk to its terminator",
    unit="s",
)

turn_time_to_first_delta_s = _turn_meter.create_histogram(
    "assistant.turn.time_to_first_delta",
    description="Time from a turn's start chunk to its first text delta",
    unit="s",
)

turn_time_to_first_tool_call_s = _turn_meter.create_histogram(
    "assistant.turn.time_to_first_tool_call",
    description="Time from a turn's start chunk to its first tool call",
    unit="s",
)

turn_tokens = _turn_meter.create_counter(
    "assistant.turn.tokens",
    description="Tokens a finished turn accounted for",
    unit="{token}",
)

sse_subscriptions = _sse_meter.create_counter(
    "assistant.sse.subscriptions",
    description="Event-stream subscriptions opened, by whether they resumed",
    unit="{subscription}",
)

sse_active_subscriptions = _sse_meter.create_up_down_counter(
    "assistant.sse.active_subscriptions",
    description="Event-stream subscriptions open now",
    unit="{subscription}",
)

sse_subscription_duration_s = _sse_meter.create_histogram(
    "assistant.sse.subscription_duration",
    description="Lifetime of one event-stream subscription",
    unit="s",
)

sse_disconnects = _sse_meter.create_counter(
    "assistant.sse.disconnects",
    description="Event-stream subscriptions closed, by reason",
    unit="{disconnect}",
)

sse_events_sent = _sse_meter.create_counter(
    "assistant.sse.events_sent",
    description="Frames served to a subscriber, by chunk kind",
    unit="{event}",
)

sse_keepalives_sent = _sse_meter.create_counter(
    "assistant.sse.keepalives_sent",
    description="Keepalive comments served to a subscriber",
    unit="{keepalive}",
)

_START = "start"
_FINISH = "finish"
_DONE = "done"
_TEXT_DELTA = "text-delta"
_TOOL_INPUT_START = "tool-input-start"


class _ObservedChunk(BaseModel):
    """The two fields of a chunk the timings read."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str = ""
    finish_reason: str = Field(default="", alias="finishReason")


def chunk_kind(chunk: Mapping[str, Any]) -> str:
    """The kind this chunk carries, as the wire spells it."""
    return _ObservedChunk.model_validate(chunk).type


class TurnTimeline:
    """What one turn's chunks say about when it answered and how it ended.

    One instance per turn. A turn whose start it never saw records nothing,
    because the writer that holds it did not open that turn.
    """

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._started_at: float | None = None
        self._first_delta = False
        self._first_tool_call = False

    def observe(self, chunk: Mapping[str, Any]) -> None:
        """Record what this chunk says about the turn."""
        observed = _ObservedChunk.model_validate(chunk)
        if observed.type == _START:
            self._started_at = self._now()
            return
        if self._started_at is None:
            return
        if observed.type == _FINISH:
            turn_runs.add(1, {"finish_reason": observed.finish_reason})
        elif observed.type == _DONE:
            turn_duration_s.record(self._now() - self._started_at)
        elif observed.type == _TEXT_DELTA and not self._first_delta:
            self._first_delta = True
            turn_time_to_first_delta_s.record(self._now() - self._started_at)
        elif observed.type == _TOOL_INPUT_START and not self._first_tool_call:
            self._first_tool_call = True
            turn_time_to_first_tool_call_s.record(self._now() - self._started_at)


class SseSubscription:
    """One reader's subscription to a thread, from its first frame to its last."""

    def __init__(
        self,
        *,
        resumed: bool,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._now = now
        self._opened_at = now()
        sse_subscriptions.add(1, {"resumed": resumed})
        sse_active_subscriptions.add(1)

    def event(self, kind: str) -> None:
        sse_events_sent.add(1, {"kind": kind})

    def keepalive(self) -> None:
        sse_keepalives_sent.add(1)

    def close(self, *, reason: str) -> None:
        sse_active_subscriptions.add(-1)
        sse_subscription_duration_s.record(self._now() - self._opened_at)
        sse_disconnects.add(1, {"reason": reason})


__all__ = [
    "SseSubscription",
    "TurnTimeline",
    "chunk_kind",
    "sse_active_subscriptions",
    "sse_disconnects",
    "sse_events_sent",
    "sse_keepalives_sent",
    "sse_subscription_duration_s",
    "sse_subscriptions",
    "turn_duration_s",
    "turn_runs",
    "turn_time_to_first_delta_s",
    "turn_time_to_first_tool_call_s",
    "turn_tokens",
]
