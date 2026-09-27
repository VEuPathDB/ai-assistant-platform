"""The identical-arguments rule ends a run only on a repeat the model issued after its warning."""

from __future__ import annotations

from assistant_core.capabilities.repetition_guard import (
    DEFAULT_REPETITION_THRESHOLD,
    ToolRepetitionGuard,
)


def _guard() -> ToolRepetitionGuard:
    return ToolRepetitionGuard(read_only_tools=frozenset({"find", "read"}))


def test_every_repeat_in_the_warned_request_gets_the_nudge() -> None:
    guard = _guard()

    blocks = [
        guard.check("find", {"q": "a"}, tool_call_id=f"call-{n}", run_step=2)
        for n in range(1, 6)
    ]

    refused = [b for b in blocks if b is not None]
    assert [b.count for b in refused] == [3, 4, 5]
    assert [b.escalated for b in refused] == [False, False, False]
    assert all("Change approach" in b.message for b in refused)
    assert guard.stopped_call_id == ""
    assert guard.stopped_rule is None
    assert guard.total_blocked == 3


def test_a_repeat_in_a_later_request_ends_the_run() -> None:
    guard = _guard()
    for step in range(1, DEFAULT_REPETITION_THRESHOLD + 1):
        guard.check("find", {"q": "a"}, tool_call_id=f"call-{step}", run_step=step)

    block = guard.check("find", {"q": "a"}, tool_call_id="call-4", run_step=4)

    assert block is not None
    assert block.count == 4
    assert block.escalated
    assert "You were already asked to change approach" in block.message
    assert "The run stops here." in block.message
    assert guard.stopped_call_id == "call-4"
    assert guard.stopped_rule == "identical_arguments"


def test_a_state_change_clears_the_warning_with_the_streak() -> None:
    guard = _guard()
    for step in (1, 2, 3):
        guard.check("find", {"q": "a"}, run_step=step)
    guard.check("write", {}, run_step=4)
    for step in (5, 6):
        guard.check("find", {"q": "a"}, run_step=step)

    block = guard.check("find", {"q": "a"}, tool_call_id="call-7", run_step=7)

    assert block is not None
    assert block.count == 3
    assert not block.escalated
    assert guard.stopped_call_id == ""


def test_a_new_argument_clears_the_warning_with_the_streak() -> None:
    guard = _guard()
    for step in (1, 2, 3):
        guard.check("find", {"q": "a"}, run_step=step)
    for step in (4, 5):
        guard.check("find", {"q": "b"}, run_step=step)

    block = guard.check("find", {"q": "b"}, tool_call_id="call-6", run_step=6)

    assert block is not None
    assert block.count == 3
    assert not block.escalated
    assert guard.stopped_call_id == ""
