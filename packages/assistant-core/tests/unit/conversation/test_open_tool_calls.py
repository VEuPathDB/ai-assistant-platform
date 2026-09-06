"""A turn that ends in error names the tool calls it left running."""

from __future__ import annotations

from typing import Any

from assistant_core.conversation.open_tool_calls import open_tool_call_ids


def _input_start(tool_call_id: str) -> dict[str, Any]:
    return {
        "type": "tool-input-start",
        "toolCallId": tool_call_id,
        "toolName": "search_eda_studies",
    }


def _input_available(tool_call_id: str) -> dict[str, Any]:
    return {
        "type": "tool-input-available",
        "toolCallId": tool_call_id,
        "toolName": "search_eda_studies",
        "input": {"limit": 5},
    }


def test_a_call_with_input_and_no_output_is_open() -> None:
    chunks = [
        {"type": "start", "messageId": "m"},
        _input_start("call-1"),
        _input_available("call-1"),
    ]

    assert open_tool_call_ids(chunks) == ["call-1"]


def test_a_call_announced_only_by_its_input_is_open() -> None:
    """A provider that skips ``tool-input-start`` still opens the call."""
    assert open_tool_call_ids([_input_available("call-1")]) == ["call-1"]


def test_a_call_with_output_is_closed() -> None:
    chunks = [
        _input_available("call-1"),
        {"type": "tool-output-available", "toolCallId": "call-1", "output": {}},
    ]

    assert open_tool_call_ids(chunks) == []


def test_a_call_with_an_output_error_is_closed() -> None:
    chunks = [
        _input_available("call-1"),
        {"type": "tool-output-error", "toolCallId": "call-1", "errorText": "boom"},
    ]

    assert open_tool_call_ids(chunks) == []


def test_a_call_waiting_on_an_approval_is_closed() -> None:
    chunks = [
        _input_available("call-1"),
        {"type": "tool-approval-request", "toolCallId": "call-1", "approvalId": "a-1"},
    ]

    assert open_tool_call_ids(chunks) == []


def test_open_calls_keep_the_order_they_opened_in() -> None:
    chunks = [
        _input_start("call-1"),
        _input_start("call-2"),
        _input_available("call-2"),
        {"type": "tool-output-available", "toolCallId": "call-2", "output": {}},
        _input_start("call-3"),
    ]

    assert open_tool_call_ids(chunks) == ["call-1", "call-3"]


def test_a_call_reopened_after_its_output_is_open_again() -> None:
    chunks = [
        _input_available("call-1"),
        {"type": "tool-output-available", "toolCallId": "call-1", "output": {}},
        _input_start("call-1"),
    ]

    assert open_tool_call_ids(chunks) == ["call-1"]


def test_chunks_that_name_no_tool_call_are_ignored() -> None:
    chunks = [
        {"type": "text-delta", "id": "t", "delta": "hello"},
        {"type": "data-turn-status", "data": {"label": "Queued"}},
        {"type": "finish", "finishReason": "error"},
    ]

    assert open_tool_call_ids(chunks) == []
