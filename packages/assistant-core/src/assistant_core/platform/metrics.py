"""The instruments the runtime records, and the readers that fill them.

A host installs the meter provider its process exports through. A process that
installs none records on the global metrics API, which is a no-op sink until
something configures it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, MeterProvider, UpDownCounter
from pydantic import BaseModel, ConfigDict, Field, field_validator


@dataclass(frozen=True, kw_only=True)
class Instruments:
    """Every series the runtime records, on one meter provider."""

    turn_runs: Counter
    turn_duration_s: Histogram
    turn_time_to_first_delta_s: Histogram
    turn_time_to_first_tool_call_s: Histogram
    turn_tokens: Counter
    sse_subscriptions: Counter
    sse_active_subscriptions: UpDownCounter
    sse_subscription_duration_s: Histogram
    sse_disconnects: Counter
    sse_events_sent: Counter
    sse_keepalives_sent: Counter


def _build(provider: MeterProvider | None) -> Instruments:
    turn_meter = metrics.get_meter("assistant.turn", meter_provider=provider)
    sse_meter = metrics.get_meter("assistant.sse", meter_provider=provider)
    return Instruments(
        turn_runs=turn_meter.create_counter(
            "assistant.turn.runs",
            description="Turns that reached a finish chunk, by finish reason",
            unit="{turn}",
        ),
        turn_duration_s=turn_meter.create_histogram(
            "assistant.turn.duration",
            description="Wall-clock time from a turn's start chunk to its terminator",
            unit="s",
        ),
        turn_time_to_first_delta_s=turn_meter.create_histogram(
            "assistant.turn.time_to_first_delta",
            description="Time from a turn's start chunk to its first text delta",
            unit="s",
        ),
        turn_time_to_first_tool_call_s=turn_meter.create_histogram(
            "assistant.turn.time_to_first_tool_call",
            description="Time from a turn's start chunk to its first tool call",
            unit="s",
        ),
        turn_tokens=turn_meter.create_counter(
            "assistant.turn.tokens",
            description="Tokens a finished turn accounted for",
            unit="{token}",
        ),
        sse_subscriptions=sse_meter.create_counter(
            "assistant.sse.subscriptions",
            description="Event-stream subscriptions opened, by whether they resumed",
            unit="{subscription}",
        ),
        sse_active_subscriptions=sse_meter.create_up_down_counter(
            "assistant.sse.active_subscriptions",
            description="Event-stream subscriptions open now",
            unit="{subscription}",
        ),
        sse_subscription_duration_s=sse_meter.create_histogram(
            "assistant.sse.subscription_duration",
            description="Lifetime of one event-stream subscription",
            unit="s",
        ),
        sse_disconnects=sse_meter.create_counter(
            "assistant.sse.disconnects",
            description="Event-stream subscriptions closed, by reason",
            unit="{disconnect}",
        ),
        sse_events_sent=sse_meter.create_counter(
            "assistant.sse.events_sent",
            description="Frames served to a subscriber, by chunk kind",
            unit="{event}",
        ),
        sse_keepalives_sent=sse_meter.create_counter(
            "assistant.sse.keepalives_sent",
            description="Keepalive comments served to a subscriber",
            unit="{keepalive}",
        ),
    )


class _InstalledProvider:
    """The provider in force, and the instruments built on it."""

    def __init__(self) -> None:
        self._provider: MeterProvider | None = None
        self._instruments: Instruments | None = None

    def use(self, provider: MeterProvider | None) -> None:
        self._provider = provider
        self._instruments = None

    def read(self) -> Instruments:
        if self._instruments is None:
            self._instruments = _build(self._provider)
        return self._instruments


_installed = _InstalledProvider()


def install_meter_provider(provider: MeterProvider) -> None:
    """Record every runtime series on this provider, for this process."""
    _installed.use(provider)


def reset_meter_provider() -> None:
    """Record on the global metrics API again, so a process can install another."""
    _installed.use(None)


def instruments() -> Instruments:
    """The instruments this process records on."""
    return _installed.read()


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

    @field_validator("finish_reason", mode="before")
    @classmethod
    def _an_unset_reason_is_empty(cls, value: str | None) -> str:
        """A finish chunk carries no reason when the model named none."""
        return value or ""


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
        recorded = instruments()
        if observed.type == _FINISH:
            recorded.turn_runs.add(1, {"finish_reason": observed.finish_reason})
        elif observed.type == _DONE:
            recorded.turn_duration_s.record(self._now() - self._started_at)
        elif observed.type == _TEXT_DELTA and not self._first_delta:
            self._first_delta = True
            recorded.turn_time_to_first_delta_s.record(self._now() - self._started_at)
        elif observed.type == _TOOL_INPUT_START and not self._first_tool_call:
            self._first_tool_call = True
            recorded.turn_time_to_first_tool_call_s.record(
                self._now() - self._started_at,
            )


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
        opened = instruments()
        opened.sse_subscriptions.add(1, {"resumed": resumed})
        opened.sse_active_subscriptions.add(1)

    def event(self, kind: str) -> None:
        instruments().sse_events_sent.add(1, {"kind": kind})

    def keepalive(self) -> None:
        instruments().sse_keepalives_sent.add(1)

    def close(self, *, reason: str) -> None:
        closed = instruments()
        closed.sse_active_subscriptions.add(-1)
        closed.sse_subscription_duration_s.record(self._now() - self._opened_at)
        closed.sse_disconnects.add(1, {"reason": reason})


def record_turn_tokens(tokens: int) -> None:
    """Add what one finished turn accounted for."""
    instruments().turn_tokens.add(tokens)


__all__ = [
    "Instruments",
    "SseSubscription",
    "TurnTimeline",
    "install_meter_provider",
    "instruments",
    "record_turn_tokens",
    "reset_meter_provider",
]
