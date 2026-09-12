"""A per-run cap bounds how often one run reads a tool, whatever the arguments."""

from __future__ import annotations

import pytest

from assistant_core.capabilities.repetition_guard import (
    CALL_CAP_MARKER,
    REPETITION_MARKER,
    ToolRepetitionGuard,
)


def _capped(cap: int) -> ToolRepetitionGuard:
    return ToolRepetitionGuard(
        read_only_tools=frozenset({"find"}),
        call_caps={"find": cap},
    )


def test_the_calls_up_to_the_cap_run() -> None:
    guard = _capped(3)

    blocks = [guard.check("find", {"q": q}) for q in ("a", "b", "c")]

    assert blocks == [None, None, None]
    assert guard.total_blocked == 0


def test_the_call_past_the_cap_is_refused_and_names_the_count() -> None:
    guard = _capped(3)
    for q in ("a", "b", "c"):
        guard.check("find", {"q": q})

    block = guard.check("find", {"q": "d"}, tool_call_id="call-4")

    assert block is not None
    assert block.tool_name == "find"
    assert block.count == 4
    assert not block.escalated
    assert CALL_CAP_MARKER in block.message
    assert "find" in block.message
    assert "4" in block.message
    assert "stop calling it" in block.message
    assert REPETITION_MARKER not in block.message
    assert guard.stopped_call_id == ""


def test_the_second_call_past_the_cap_ends_the_run() -> None:
    guard = _capped(3)
    for q in ("a", "b", "c", "d"):
        guard.check("find", {"q": q})

    block = guard.check("find", {"q": "e"}, tool_call_id="call-5")

    assert block is not None
    assert block.escalated
    assert "The run stops here." in block.message
    assert guard.stopped_call_id == "call-5"
    assert guard.total_blocked == 2


def test_a_tool_outside_the_map_is_never_capped() -> None:
    guard = ToolRepetitionGuard(call_caps={"find": 1})

    blocks = [guard.check("browse", {"q": q}) for q in "abcdefgh"]

    assert blocks == [None] * 8


def test_the_cap_is_a_budget_that_an_intervening_call_does_not_reset() -> None:
    guard = _capped(2)
    guard.check("find", {"q": "a"})
    guard.check("write", {})
    guard.check("find", {"q": "b"})
    guard.check("write", {})

    block = guard.check("find", {"q": "c"})

    assert block is not None
    assert block.count == 3


def test_the_identical_argument_refusal_keeps_its_own_marker() -> None:
    guard = ToolRepetitionGuard(read_only_tools=frozenset({"find"}))
    guard.check("find", {"q": "a"})
    guard.check("find", {"q": "a"})

    block = guard.check("find", {"q": "a"})

    assert block is not None
    assert REPETITION_MARKER in block.message
    assert CALL_CAP_MARKER not in block.message


def test_a_guard_with_no_caps_blocks_only_on_identical_arguments() -> None:
    guard = ToolRepetitionGuard(read_only_tools=frozenset({"find"}))

    blocks = [guard.check("find", {"q": q}) for q in "abcdefgh"]

    assert blocks == [None] * 8


def test_a_negative_cap_is_refused_when_the_guard_is_built() -> None:
    with pytest.raises(ValueError, match="cannot be negative: find, read"):
        ToolRepetitionGuard(call_caps={"read": -1, "find": -2})


def test_a_cap_of_zero_refuses_the_first_call_with_the_nudge() -> None:
    guard = ToolRepetitionGuard(call_caps={"find": 0})

    first = guard.check("find", {}, tool_call_id="call-1")
    second = guard.check("find", {}, tool_call_id="call-2")

    assert first is not None
    assert not first.escalated
    assert second is not None
    assert second.escalated
    assert guard.stopped_call_id == "call-2"
