"""The runtime refuses a tool call the run keeps repeating unchanged.

The synthetic assistant's loop arc asks for one reading five times. The guard
refuses the third, and ends the turn on the fourth rather than letting the
run spend the rest of its budget on the same answer.
"""

from __future__ import annotations

from tests.synthetic import LOOP_CALLS, LOOP_PROMPT, LOOP_TOOL, SyntheticRuntime

from assistant_core.capabilities.repetition_guard import (
    DEFAULT_REPETITION_THRESHOLD,
)
from assistant_core.conversation.event_stream import fetch_chunks_after


async def test_the_repeated_call_is_refused_with_the_reason(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(LOOP_PROMPT)

    # The refusal is ordinary tool output, never an error or a ModelRetry:
    # a retry raised by the guard shares the tool's retry budget and a tool
    # that already retried once would abort the run on the guard's nudge.
    outputs = [c for c in outcome.chunks if c["type"] == "tool-output-available"]
    refusals = [
        c
        for c in outputs
        if f"called {LOOP_TOOL} {DEFAULT_REPETITION_THRESHOLD} times"
        in str(c["output"])
    ]
    assert len(refusals) == 1
    assert "identical arguments" in str(refusals[0]["output"])
    assert [c for c in outcome.chunks if c["type"] == "tool-output-error"] == []


async def test_the_calls_before_the_threshold_run_normally(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(LOOP_PROMPT)

    outputs = [c for c in outcome.chunks if c["type"] == "tool-output-available"]
    assert [c["output"] for c in outputs[: DEFAULT_REPETITION_THRESHOLD - 1]] == [
        "unchanged",
    ] * (DEFAULT_REPETITION_THRESHOLD - 1)


async def test_the_turn_ends_on_the_second_refusal_rather_than_looping(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(LOOP_PROMPT)

    calls = [c for c in outcome.chunks if c["type"] == "tool-input-available"]
    assert [c["toolName"] for c in calls] == [LOOP_TOOL] * (
        DEFAULT_REPETITION_THRESHOLD + 1
    )
    assert len(calls) < LOOP_CALLS


async def test_the_stopped_turn_finishes_cleanly(
    runtime: SyntheticRuntime,
) -> None:
    await runtime.run(LOOP_PROMPT)

    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    types = [c["type"] for c in logged]

    assert "error" not in types
    assert types[-2:] == ["finish", "done"]
    assert logged[-2]["finishReason"] == "stop"


async def test_the_escalation_says_why_the_run_stopped(
    runtime: SyntheticRuntime,
) -> None:
    outcome = await runtime.run(LOOP_PROMPT)

    outputs = [c for c in outcome.chunks if c["type"] == "tool-output-available"]
    assert "stops here" in str(outputs[-1]["output"])


async def test_a_guard_that_watches_nothing_leaves_the_arc_alone(
    runtime: SyntheticRuntime,
) -> None:
    """Only the tools the assistant named are guarded; the rest are silent."""
    outcome = await runtime.run("please add")

    assert [c for c in outcome.chunks if c["type"] == "tool-output-error"] == []
