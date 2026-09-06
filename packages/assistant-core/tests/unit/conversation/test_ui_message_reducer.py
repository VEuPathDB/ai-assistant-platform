from __future__ import annotations

from assistant_core.conversation.ui_message_reducer import (
    reduce_chunks,
    split_into_turns,
    user_message_chunk,
)


def test_text_only_turn_builds_one_text_part() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "start-step"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "Hello "},
        {"type": "text-delta", "id": "t1", "delta": "world"},
        {"type": "text-end", "id": "t1"},
        {"type": "finish-step"},
        {"type": "finish"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    assert msg["id"] == "m1"
    assert msg["role"] == "assistant"
    text_parts = [p for p in msg["parts"] if p["type"] == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"] == "Hello world"
    assert text_parts[0]["state"] == "done"


def test_tool_call_lifecycle_to_output() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "tool-input-start",
            "toolCallId": "c1",
            "toolName": "get_strategy",
        },
        {
            "type": "tool-input-delta",
            "toolCallId": "c1",
            "inputTextDelta": '{"summary',
        },
        {
            "type": "tool-input-delta",
            "toolCallId": "c1",
            "inputTextDelta": '_only":true}',
        },
        {
            "type": "tool-input-available",
            "toolCallId": "c1",
            "toolName": "get_strategy",
            "input": {"summary_only": True},
        },
        {
            "type": "tool-output-available",
            "toolCallId": "c1",
            "output": {"stepCount": 5},
        },
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    tool_parts = [p for p in msg["parts"] if p["type"] == "tool-get_strategy"]
    assert len(tool_parts) == 1
    assert tool_parts[0]["state"] == "output-available"
    assert tool_parts[0]["input"] == {"summary_only": True}
    assert tool_parts[0]["output"] == {"stepCount": 5}


def test_tool_output_error_carries_error_text() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "tool-input-available",
            "toolCallId": "c1",
            "toolName": "build_strategy",
            "input": {},
        },
        {
            "type": "tool-output-error",
            "toolCallId": "c1",
            "errorText": "VALIDATION_ERROR: missing field",
        },
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    part = next(p for p in msg["parts"] if p.get("toolCallId") == "c1")
    assert part["state"] == "output-error"
    assert part["errorText"] == "VALIDATION_ERROR: missing field"


def test_data_part_dedupes_by_id() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "data-graph-snapshot",
            "id": "g1",
            "data": {"isBuilt": False},
        },
        {
            "type": "data-graph-snapshot",
            "id": "g1",
            "data": {"isBuilt": True, "stepCount": 3},
        },
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    snapshots = [p for p in msg["parts"] if p["type"] == "data-graph-snapshot"]
    assert len(snapshots) == 1
    assert snapshots[0]["data"] == {"isBuilt": True, "stepCount": 3}


def test_data_part_transient_does_not_persist() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "data-turn-usage",
            "data": {"totalTokens": 42, "costUsd": "0.001"},
            "transient": True,
        },
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    usage = [p for p in msg["parts"] if p["type"] == "data-turn-usage"]
    assert usage == []


def test_data_part_without_id_appends_new() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "data-supervisor-decision", "data": {"to": "scoping"}},
        {"type": "data-supervisor-decision", "data": {"to": "discovery"}},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    decisions = [p for p in msg["parts"] if p["type"] == "data-supervisor-decision"]
    assert len(decisions) == 2
    assert [d["data"]["to"] for d in decisions] == ["scoping", "discovery"]


def test_finish_step_clears_active_text_parts() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "first"},
        {"type": "text-end", "id": "t1"},
        {"type": "finish-step"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "second"},
        {"type": "text-end", "id": "t1"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    texts = [p["text"] for p in msg["parts"] if p["type"] == "text"]
    assert texts == ["first", "second"]


def test_split_into_turns_separates_per_done() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "a"},
        {"type": "text-end", "id": "t1"},
        {"type": "done"},
        {"type": "start", "messageId": "m2"},
        {"type": "text-start", "id": "t2"},
        {"type": "text-delta", "id": "t2", "delta": "b"},
        {"type": "text-end", "id": "t2"},
        {"type": "done"},
    ]
    turns = split_into_turns(chunks)
    assert len(turns) == 2
    assert turns[0][-1]["type"] == "done"
    assert turns[1][-1]["type"] == "done"


def test_split_keeps_in_flight_trailing_slice() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-end", "id": "t1"},
        {"type": "done"},
        {"type": "start", "messageId": "m2"},
        {"type": "text-start", "id": "t2"},
        {"type": "text-delta", "id": "t2", "delta": "incomplete"},
    ]
    turns = split_into_turns(chunks)
    assert len(turns) == 2
    assert turns[1][-1]["type"] == "text-delta"


def test_start_chunk_overwrites_message_id() -> None:
    chunks = [
        {"type": "start", "messageId": "first"},
        {"type": "text-start", "id": "t1"},
        {"type": "text-end", "id": "t1"},
        {"type": "start", "messageId": "second"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    assert msg["id"] == "second"


def test_finish_carries_finish_reason_through_done() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "finish", "finishReason": "stop"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    assert all(
        not isinstance(p.get("type"), str) or not p["type"].startswith("finish")
        for p in msg["parts"]
    )


def test_unknown_chunk_type_is_ignored() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {"type": "wat-is-this", "foo": "bar"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    assert msg["parts"] == []


def test_tool_approval_request_marks_part() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "tool-input-available",
            "toolCallId": "c1",
            "toolName": "submit_plan",
            "input": {"plan_id": "p1"},
        },
        {
            "type": "tool-approval-request",
            "toolCallId": "c1",
            "approvalId": "a1",
        },
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    part = next(p for p in msg["parts"] if p.get("toolCallId") == "c1")
    assert part["state"] == "approval-requested"
    assert part["approval"] == {"id": "a1"}


def test_user_message_chunk_does_not_pollute_assistant_parts() -> None:
    chunks = [
        {"type": "start", "messageId": "a1"},
        {"type": "text-start", "id": "t1"},
        user_message_chunk(message_id="u_mid", parts=[]),
        {"type": "text-delta", "id": "t1", "delta": "uninterrupted"},
        {"type": "text-end", "id": "t1"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    assert msg["role"] == "assistant"
    text_parts = [p for p in msg["parts"] if p["type"] == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"] == "uninterrupted"


def test_tool_output_denied_marks_part() -> None:
    chunks = [
        {"type": "start", "messageId": "m1"},
        {
            "type": "tool-input-available",
            "toolCallId": "c1",
            "toolName": "delete_step",
            "input": {"step_id": "s1"},
        },
        {"type": "tool-output-denied", "toolCallId": "c1"},
        {"type": "done"},
    ]
    msg = reduce_chunks(chunks, "fallback")
    part = next(p for p in msg["parts"] if p.get("toolCallId") == "c1")
    assert part["state"] == "output-denied"
