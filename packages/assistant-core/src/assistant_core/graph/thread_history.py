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
    ModelRequest,
    ModelResponse,
    ToolReturnPart,
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


def _returns_every_call(response: ModelMessage, results: ModelMessage) -> bool:
    if not isinstance(response, ModelResponse) or not isinstance(results, ModelRequest):
        return False
    returned = {
        part.tool_call_id for part in results.parts if isinstance(part, ToolReturnPart)
    }
    called = {call.tool_call_id for call in response.tool_calls}
    return bool(called) and called <= returned


def _settled(messages: list[ModelMessage]) -> bool:
    return _ends_an_exchange(messages[-1]) or (
        len(messages) > 1 and _returns_every_call(messages[-2], messages[-1])
    )


def settled_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """``messages`` up to the last answer that left no call outstanding."""
    kept = list(messages)
    while kept and not _settled(kept):
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
