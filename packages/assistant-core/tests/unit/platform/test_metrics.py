"""The instruments record what the runtime's own emitters see.

The reader is installed once for the process, and reads deltas, so each test
collects only the points it produced.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import (
    Counter,
    Histogram,
    MeterProvider,
    UpDownCounter,
)
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    InMemoryMetricReader,
)

from assistant_core.platform.metrics import SseSubscription, TurnTimeline

_READER = InMemoryMetricReader(
    preferred_temporality={
        Counter: AggregationTemporality.DELTA,
        Histogram: AggregationTemporality.DELTA,
        UpDownCounter: AggregationTemporality.DELTA,
    },
)
metrics.set_meter_provider(MeterProvider(metric_readers=[_READER]))


def _recorded() -> dict[str, list[Any]]:
    """Every point collected since the last read, by instrument name."""
    collected = _READER.get_metrics_data()
    points: dict[str, list[Any]] = {}
    if collected is None:
        return points
    for resource in collected.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


def test_a_turn_records_its_duration_and_its_outcome() -> None:
    clock = iter([0.0, 1.5, 4.0])
    timeline = TurnTimeline(now=lambda: next(clock))

    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "text-delta", "delta": "hi"})
    timeline.observe({"type": "finish", "finishReason": "stop"})
    timeline.observe({"type": "done"})

    points = _recorded()
    assert [point.value for point in points["assistant.turn.runs"]] == [1]
    assert points["assistant.turn.runs"][0].attributes["finish_reason"] == "stop"
    assert points["assistant.turn.time_to_first_delta"][0].sum == 1.5
    assert points["assistant.turn.duration"][0].sum == 4.0


def test_only_the_first_delta_and_the_first_tool_call_are_timed() -> None:
    clock = iter([0.0, 2.0, 3.0])
    timeline = TurnTimeline(now=lambda: next(clock))

    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "tool-input-start", "toolCallId": "c1"})
    timeline.observe({"type": "tool-input-start", "toolCallId": "c2"})
    timeline.observe({"type": "text-delta", "delta": "a"})
    timeline.observe({"type": "text-delta", "delta": "b"})

    points = _recorded()
    assert points["assistant.turn.time_to_first_tool_call"][0].count == 1
    assert points["assistant.turn.time_to_first_tool_call"][0].sum == 2.0
    assert points["assistant.turn.time_to_first_delta"][0].count == 1
    assert points["assistant.turn.time_to_first_delta"][0].sum == 3.0


def test_a_turn_whose_start_the_writer_never_saw_records_nothing() -> None:
    timeline = TurnTimeline(now=lambda: 1.0)

    timeline.observe({"type": "text-delta", "delta": "hi"})
    timeline.observe({"type": "finish", "finishReason": "stop"})
    timeline.observe({"type": "done"})

    points = _recorded()
    assert "assistant.turn.duration" not in points
    assert "assistant.turn.runs" not in points


def test_a_subscription_records_its_frames_and_how_it_ended() -> None:
    clock = iter([0.0, 7.0])
    subscription = SseSubscription(resumed=True, now=lambda: next(clock))

    subscription.event("text-delta")
    subscription.event("text-delta")
    subscription.keepalive()
    subscription.close(reason="turn-end")

    points = _recorded()
    assert points["assistant.sse.subscriptions"][0].attributes["resumed"] is True
    assert [point.value for point in points["assistant.sse.events_sent"]] == [2]
    assert [point.value for point in points["assistant.sse.keepalives_sent"]] == [1]
    assert points["assistant.sse.subscription_duration"][0].sum == 7.0
    assert points["assistant.sse.disconnects"][0].attributes["reason"] == "turn-end"
    assert [point.value for point in points["assistant.sse.active_subscriptions"]] == [
        0
    ]
