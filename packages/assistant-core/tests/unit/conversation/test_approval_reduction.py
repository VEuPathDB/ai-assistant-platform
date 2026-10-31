from __future__ import annotations

from typing import Any

from assistant_core.conversation.ui_message_reducer import reduce_chunks

MESSAGE = "aaaaaaaa-0000-4000-8000-000000000001"
CALL = "call_wipe"
APPROVAL = "approval_wipe"
INPUT = {"target": "everything"}

ASKED: list[dict[str, Any]] = [
    {"type": "start", "messageId": MESSAGE},
    {"type": "tool-input-start", "toolCallId": CALL, "toolName": "wipe"},
    {
        "type": "tool-input-available",
        "toolCallId": CALL,
        "toolName": "wipe",
        "input": INPUT,
    },
    {"type": "tool-approval-request", "toolCallId": CALL, "approvalId": APPROVAL},
    {"type": "finish", "finishReason": "other"},
    {"type": "done"},
]


def _answered(*outcome: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"type": "start", "messageId": MESSAGE},
        {
            "type": "tool-input-available",
            "toolCallId": CALL,
            "toolName": "wipe",
            "input": INPUT,
        },
        *outcome,
        {"type": "finish", "finishReason": "stop"},
        {"type": "done"},
    ]


def _call(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    parts = reduce_chunks(chunks, default_message_id=MESSAGE)["parts"]
    assert len(parts) == 1
    part: dict[str, Any] = parts[0]
    return part


def test_an_approved_call_keeps_its_approval_once_its_output_arrives() -> None:
    part = _call(
        [
            *ASKED,
            *_answered(
                {
                    "type": "tool-output-available",
                    "toolCallId": CALL,
                    "output": "wiped everything",
                }
            ),
        ]
    )

    assert part == {
        "type": "tool-wipe",
        "toolCallId": CALL,
        "state": "output-available",
        "input": INPUT,
        "output": "wiped everything",
        "approval": {"id": APPROVAL, "approved": True},
    }


def test_an_approved_call_that_fails_keeps_its_approval() -> None:
    part = _call(
        [
            *ASKED,
            *_answered(
                {"type": "tool-output-error", "toolCallId": CALL, "errorText": "boom"}
            ),
        ]
    )

    assert part["state"] == "output-error"
    assert part["approval"] == {"id": APPROVAL, "approved": True}


def test_a_re_entered_call_carries_no_approval_while_it_runs() -> None:
    part = _call([*ASKED, *_answered()[:2]])

    assert part["state"] == "input-available"
    assert "approval" not in part


def test_a_refused_call_keeps_its_approval_as_a_refusal() -> None:
    part = _call(
        [*ASKED, *_answered({"type": "tool-output-denied", "toolCallId": CALL})]
    )

    assert part["state"] == "output-denied"
    assert part["approval"] == {"id": APPROVAL, "approved": False}


def test_a_call_that_asked_for_no_approval_has_no_approval_key() -> None:
    part = _call(
        [
            {"type": "start", "messageId": MESSAGE},
            {
                "type": "tool-input-available",
                "toolCallId": CALL,
                "toolName": "wipe",
                "input": INPUT,
            },
            {"type": "tool-output-available", "toolCallId": CALL, "output": "done"},
        ]
    )

    assert part["state"] == "output-available"
    assert "approval" not in part
