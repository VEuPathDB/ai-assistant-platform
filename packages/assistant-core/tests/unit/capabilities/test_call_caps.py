"""A per-run cap bounds how often one run reads a tool, whatever the arguments."""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assistant_core.capabilities.repetition_guard import (
    CALL_CAP_MARKER,
    REPETITION_MARKER,
    RepetitionGuard,
    ToolRepetitionGuard,
)


def _capped(cap: int) -> ToolRepetitionGuard:
    return ToolRepetitionGuard(
        read_only_tools=frozenset({"find"}),
        call_caps={"find": cap},
    )


def test_the_calls_up_to_the_cap_run() -> None:
    guard = _capped(3)

    blocks = [guard.check("find", {"q": q}, run_step=1) for q in ("a", "b", "c")]

    assert blocks == [None, None, None]
    assert guard.total_blocked == 0


def test_the_call_past_the_cap_is_refused_and_names_the_count() -> None:
    guard = _capped(3)
    for q in ("a", "b", "c"):
        guard.check("find", {"q": q}, run_step=1)

    block = guard.check("find", {"q": "d"}, tool_call_id="call-4", run_step=2)

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
    assert guard.stopped_rule is None


def test_a_call_past_the_cap_in_a_later_request_ends_the_run() -> None:
    guard = _capped(3)
    for q in ("a", "b", "c", "d"):
        guard.check("find", {"q": q}, run_step=1)

    block = guard.check("find", {"q": "e"}, tool_call_id="call-5", run_step=2)

    assert block is not None
    assert block.escalated
    assert "The run stops here." in block.message
    assert guard.stopped_call_id == "call-5"
    assert guard.stopped_rule == "call_cap"
    assert guard.total_blocked == 2


def test_every_call_past_the_cap_in_the_warned_request_gets_the_nudge() -> None:
    guard = _capped(8)

    blocks = [
        guard.check("read", {"id": n}, tool_call_id=f"call-{n}", run_step=3)
        for n in range(1, 11)
    ] + [
        guard.check("find", {"q": n}, tool_call_id=f"call-{n}", run_step=3)
        for n in range(1, 11)
    ]

    refused = [b for b in blocks if b is not None]
    assert [b.count for b in refused] == [9, 10]
    assert [b.escalated for b in refused] == [False, False]
    assert all("stop calling it" in b.message for b in refused)
    assert guard.stopped_call_id == ""
    assert guard.total_blocked == 2


def test_the_first_call_past_the_cap_after_the_warned_request_ends_the_run() -> None:
    guard = _capped(8)
    for n in range(1, 11):
        guard.check("find", {"q": n}, tool_call_id=f"call-{n}", run_step=3)

    block = guard.check("find", {"q": 11}, tool_call_id="call-11", run_step=4)
    after = guard.check("find", {"q": 12}, tool_call_id="call-12", run_step=4)

    assert block is not None
    assert block.count == 11
    assert block.escalated
    assert after is not None
    assert after.escalated
    assert guard.stopped_call_id == "call-11"
    assert guard.stopped_rule == "call_cap"


def test_a_tool_outside_the_map_is_never_capped() -> None:
    guard = ToolRepetitionGuard(call_caps={"find": 1})

    blocks = [guard.check("browse", {"q": q}, run_step=1) for q in "abcdefgh"]

    assert blocks == [None] * 8


def test_the_cap_is_a_budget_that_an_intervening_call_does_not_reset() -> None:
    guard = _capped(2)
    guard.check("find", {"q": "a"}, run_step=1)
    guard.check("write", {}, run_step=1)
    guard.check("find", {"q": "b"}, run_step=2)
    guard.check("write", {}, run_step=2)

    block = guard.check("find", {"q": "c"}, run_step=3)

    assert block is not None
    assert block.count == 3


def test_the_identical_argument_refusal_keeps_its_own_marker() -> None:
    guard = ToolRepetitionGuard(read_only_tools=frozenset({"find"}))
    guard.check("find", {"q": "a"}, run_step=1)
    guard.check("find", {"q": "a"}, run_step=2)

    block = guard.check("find", {"q": "a"}, run_step=3)

    assert block is not None
    assert REPETITION_MARKER in block.message
    assert CALL_CAP_MARKER not in block.message


def test_a_guard_with_no_caps_blocks_only_on_identical_arguments() -> None:
    guard = ToolRepetitionGuard(read_only_tools=frozenset({"find"}))

    blocks = [guard.check("find", {"q": q}, run_step=1) for q in "abcdefgh"]

    assert blocks == [None] * 8


def test_a_negative_cap_is_refused_when_the_guard_is_built() -> None:
    with pytest.raises(ValueError, match="cannot be negative: find, read"):
        ToolRepetitionGuard(call_caps={"read": -1, "find": -2})


def test_a_cap_of_zero_refuses_the_first_call_with_the_nudge() -> None:
    guard = ToolRepetitionGuard(call_caps={"find": 0})

    first = guard.check("find", {}, tool_call_id="call-1", run_step=1)
    sibling = guard.check("find", {}, tool_call_id="call-2", run_step=1)
    second = guard.check("find", {}, tool_call_id="call-3", run_step=2)

    assert first is not None
    assert not first.escalated
    assert sibling is not None
    assert not sibling.escalated
    assert second is not None
    assert second.escalated
    assert guard.stopped_call_id == "call-3"


def _batch_then_one_more(
    messages: list[ModelMessage], info: AgentInfo
) -> ModelResponse:
    del info
    requests = sum(1 for m in messages if m.kind == "request")
    if requests == 1:
        return ModelResponse(
            parts=[
                ToolCallPart("find", {"q": n}, tool_call_id=f"call-{n}")
                for n in range(1, 11)
            ]
        )
    if requests == 2:
        return ModelResponse(
            parts=[ToolCallPart("find", {"q": 11}, tool_call_id="call-11")]
        )
    return ModelResponse(parts=[TextPart("done")])


async def test_the_capability_reads_the_request_step_of_the_run() -> None:
    guard = _capped(8)
    agent = Agent(
        FunctionModel(_batch_then_one_more),
        capabilities=[RepetitionGuard(guard=guard)],
    )

    @agent.tool_plain
    def find(q: int) -> str:
        return f"found {q}"

    result = await agent.run("go")

    returns = {
        part.tool_call_id: str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }
    assert returns["call-8"] == "found 8"
    assert "stop calling it" in returns["call-9"]
    assert "stop calling it" in returns["call-10"]
    assert "The run stops here." not in returns["call-9"]
    assert "The run stops here." not in returns["call-10"]
    assert "The run stops here." in returns["call-11"]
    assert guard.stopped_call_id == "call-11"
    assert guard.stopped_rule == "call_cap"
