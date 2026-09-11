"""The instruments record what the runtime's own emitters see.

Each test installs a meter provider of its own, so the points it reads are the
points it produced and not what another suite recorded first.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
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

from assistant_core.platform.metrics import (
    SseSubscription,
    TurnTimeline,
    install_meter_provider,
    reset_meter_provider,
)

_DELTAS = {
    Counter: AggregationTemporality.DELTA,
    Histogram: AggregationTemporality.DELTA,
    UpDownCounter: AggregationTemporality.DELTA,
}


@contextmanager
def _installed() -> Iterator[InMemoryMetricReader]:
    """Record on a provider this block owns, and give the global one back."""
    collector = InMemoryMetricReader(preferred_temporality=_DELTAS)
    provider = MeterProvider(metric_readers=[collector])
    install_meter_provider(provider)
    try:
        yield collector
    finally:
        reset_meter_provider()
        provider.shutdown()


@pytest.fixture
def reader() -> Generator[InMemoryMetricReader]:
    """A reader this test owns, installed for the length of the test."""
    with _installed() as collector:
        yield collector


def _recorded(collector: InMemoryMetricReader) -> dict[str, list[Any]]:
    """Every point this reader collected, by instrument name."""
    collected = collector.get_metrics_data()
    points: dict[str, list[Any]] = {}
    if collected is None:
        return points
    for resource in collected.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


def test_a_turn_records_its_duration_and_its_outcome(
    reader: InMemoryMetricReader,
) -> None:
    clock = iter([0.0, 1.5, 4.0])
    timeline = TurnTimeline(now=lambda: next(clock))

    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "text-delta", "delta": "hi"})
    timeline.observe({"type": "finish", "finishReason": "stop"})
    timeline.observe({"type": "done"})

    points = _recorded(reader)
    assert [point.value for point in points["assistant.turn.runs"]] == [1]
    assert points["assistant.turn.runs"][0].attributes["finish_reason"] == "stop"
    assert points["assistant.turn.time_to_first_delta"][0].sum == 1.5
    assert points["assistant.turn.duration"][0].sum == 4.0


def test_a_finish_chunk_that_names_no_reason_is_still_recorded(
    reader: InMemoryMetricReader,
) -> None:
    """The wire type allows a null reason, and the counter reads it as unnamed."""
    timeline = TurnTimeline(now=lambda: 0.0)

    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "finish", "finishReason": None})

    points = _recorded(reader)
    assert [point.value for point in points["assistant.turn.runs"]] == [1]
    assert points["assistant.turn.runs"][0].attributes["finish_reason"] == ""


def test_only_the_first_delta_and_the_first_tool_call_are_timed(
    reader: InMemoryMetricReader,
) -> None:
    clock = iter([0.0, 2.0, 3.0])
    timeline = TurnTimeline(now=lambda: next(clock))

    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "tool-input-start", "toolCallId": "c1"})
    timeline.observe({"type": "tool-input-start", "toolCallId": "c2"})
    timeline.observe({"type": "text-delta", "delta": "a"})
    timeline.observe({"type": "text-delta", "delta": "b"})

    points = _recorded(reader)
    assert points["assistant.turn.time_to_first_tool_call"][0].count == 1
    assert points["assistant.turn.time_to_first_tool_call"][0].sum == 2.0
    assert points["assistant.turn.time_to_first_delta"][0].count == 1
    assert points["assistant.turn.time_to_first_delta"][0].sum == 3.0


def test_a_turn_whose_start_the_writer_never_saw_records_nothing(
    reader: InMemoryMetricReader,
) -> None:
    timeline = TurnTimeline(now=lambda: 1.0)

    timeline.observe({"type": "text-delta", "delta": "hi"})
    timeline.observe({"type": "finish", "finishReason": "stop"})
    timeline.observe({"type": "done"})

    points = _recorded(reader)
    assert "assistant.turn.duration" not in points
    assert "assistant.turn.runs" not in points


def test_a_subscription_records_its_frames_and_how_it_ended(
    reader: InMemoryMetricReader,
) -> None:
    clock = iter([0.0, 7.0])
    subscription = SseSubscription(resumed=True, now=lambda: next(clock))

    subscription.event("text-delta")
    subscription.event("text-delta")
    subscription.keepalive()
    subscription.close(reason="turn-end")

    points = _recorded(reader)
    assert points["assistant.sse.subscriptions"][0].attributes["resumed"] is True
    assert [point.value for point in points["assistant.sse.events_sent"]] == [2]
    assert [point.value for point in points["assistant.sse.keepalives_sent"]] == [1]
    assert points["assistant.sse.subscription_duration"][0].sum == 7.0
    assert points["assistant.sse.disconnects"][0].attributes["reason"] == "turn-end"
    assert [point.value for point in points["assistant.sse.active_subscriptions"]] == [
        0
    ]


def _one_turn() -> None:
    timeline = TurnTimeline(now=lambda: 0.0)
    timeline.observe({"type": "start", "messageId": "m"})
    timeline.observe({"type": "finish", "finishReason": "stop"})


def test_a_turn_recorded_before_a_reader_is_installed_stays_out_of_it() -> None:
    """Whatever the rest of a suite records, a reader holds its own turns only."""
    with _installed() as first:
        _one_turn()
        with _installed() as second:
            _one_turn()
            assert [
                point.value for point in _recorded(second)["assistant.turn.runs"]
            ] == [1]
        assert [point.value for point in _recorded(first)["assistant.turn.runs"]] == [1]
