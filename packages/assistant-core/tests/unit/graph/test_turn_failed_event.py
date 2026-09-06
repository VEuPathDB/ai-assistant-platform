from assistant_core.conversation.stream_parts.core_parts import (
    register_core_stream_parts,
)
from assistant_core.conversation.stream_parts.registry import StreamPartRegistry
from assistant_core.conversation.ui_message_reducer import reduce_chunks
from assistant_core.graph.stream_events import turn_failed_event


def test_turn_failed_event_carries_the_error_text() -> None:
    chunk = turn_failed_event(error_text="The worker stopped before it finished.")
    assert chunk.type == "data-turn-failed"
    assert chunk.data == {"errorText": "The worker stopped before it finished."}


def test_turn_failed_is_a_registered_stream_part() -> None:
    registry = StreamPartRegistry()
    register_core_stream_parts(registry)
    assert "data-turn-failed" in registry.kinds()


def test_turn_failed_survives_reduction_as_a_message_part() -> None:
    """The part is durable, so a transcript rebuilt from the log still holds it."""
    message = reduce_chunks(
        [
            {"type": "start", "messageId": "a1"},
            {"type": "text-start", "id": "t"},
            {"type": "text-delta", "id": "t", "delta": "Looking at PlasmoDB kinases"},
            {"type": "text-end", "id": "t"},
            {"type": "error", "errorText": "the worker stopped"},
            turn_failed_event(error_text="the worker stopped").model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
            {"type": "finish", "finishReason": "error"},
            {"type": "done"},
        ],
        "fallback",
    )

    assert message["parts"][-1] == {
        "type": "data-turn-failed",
        "data": {"errorText": "the worker stopped"},
    }
