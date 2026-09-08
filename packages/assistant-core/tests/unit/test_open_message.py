"""What a snapshot reports about the message its last turn left open."""

from __future__ import annotations

from typing import Any

from assistant_core.conversation.ui_message_reducer import open_message_of

SUSPENDED = "33333333-3333-3333-3333-333333333333"


def _suspending_turn(first: int) -> list[tuple[int, dict[str, Any]]]:
    return [
        (first, {"type": "user-message", "message": {"id": "u1", "role": "user"}}),
        (first + 1, {"type": "start", "messageId": SUSPENDED}),
        (first + 2, {"type": "data-background-task-started", "data": {"taskId": "t"}}),
        (first + 3, {"type": "finish", "finishReason": "other"}),
        (first + 4, {"type": "done"}),
    ]


def test_a_suspended_turn_names_the_cursor_before_its_start() -> None:
    open_message = open_message_of(_suspending_turn(41))

    assert open_message is not None
    assert open_message.message_id == SUSPENDED
    assert open_message.after == 41


def test_a_turn_that_ran_to_completion_leaves_no_open_message() -> None:
    entries: list[tuple[int, dict[str, Any]]] = [
        (7, {"type": "start", "messageId": SUSPENDED}),
        (8, {"type": "finish", "finishReason": "stop"}),
        (9, {"type": "done"}),
    ]

    assert open_message_of(entries) is None


def test_a_turn_with_no_finish_leaves_its_message_open() -> None:
    entries: list[tuple[int, dict[str, Any]]] = [
        (7, {"type": "done"}),
        (8, {"type": "start", "messageId": SUSPENDED}),
        (9, {"type": "text-start", "id": "t1"}),
    ]

    open_message = open_message_of(entries)

    assert open_message is not None
    assert open_message.after == 7


def test_the_last_start_wins_over_a_message_an_earlier_turn_closed() -> None:
    entries: list[tuple[int, dict[str, Any]]] = [
        (1, {"type": "start", "messageId": "earlier"}),
        (2, {"type": "finish", "finishReason": "stop"}),
        (3, {"type": "done"}),
        *_suspending_turn(4),
    ]

    open_message = open_message_of(entries)

    assert open_message is not None
    assert open_message.message_id == SUSPENDED
    assert open_message.after == 4


def test_an_empty_log_reports_no_open_message() -> None:
    assert open_message_of([]) is None


def test_the_reference_carries_the_two_fields_a_tail_needs() -> None:
    open_message = open_message_of(_suspending_turn(41))

    assert open_message is not None
    assert open_message.model_dump(by_alias=True) == {
        "messageId": SUSPENDED,
        "after": 41,
    }
