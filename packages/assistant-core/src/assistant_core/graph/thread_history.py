"""The thread's own messages, carried from one turn to the next.

The checkpoint holds them as JSON, the way a parked approval holds the run it
resumes. A thread carries whole exchanges: it ends on an answer, because
pydantic-ai refuses a new prompt over a history whose tool calls have no
results.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
)


def _ends_an_exchange(message: ModelMessage) -> bool:
    """True when pydantic-ai accepts a new prompt over ``message`` as the tail.

    ``UserPromptNode`` refuses two tails: a response holding tool calls, and a
    response the provider paused.
    """
    return (
        isinstance(message, ModelResponse)
        and not message.tool_calls
        and message.state != "suspended"
    )


def settled_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """``messages`` up to the last answer that left no call outstanding."""
    kept = list(messages)
    while kept and not _ends_an_exchange(kept[-1]):
        kept.pop()
    return kept


def dump_thread_history(messages: list[ModelMessage]) -> str:
    return ModelMessagesTypeAdapter.dump_json(settled_history(messages)).decode()


def thread_history(messages_json: str) -> list[ModelMessage] | None:
    """The thread's prior messages, and nothing on its first turn."""
    if not messages_json:
        return None
    return ModelMessagesTypeAdapter.validate_json(messages_json) or None


__all__ = ["dump_thread_history", "settled_history", "thread_history"]
