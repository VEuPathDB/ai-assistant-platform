from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

KEEP_RECENT_TOOL_PAIRS = 3

_ELIDE_MIN_CHARS = 400
"""Results at or below this stay whole: a count or an id costs less to keep
than a round trip to fetch it again."""

_ELIDE_DIGEST_CHARS = 220

_ELIDED_MARKER = "<elided to control context size"


def _digest(content: object) -> str:
    """Compress a bulky result, keeping the head so its counts and ids stay
    answerable from history."""
    try:
        rendered = content if isinstance(content, str) else json.dumps(content)
    except TypeError, ValueError:
        rendered = str(content)
    head = rendered[:_ELIDE_DIGEST_CHARS]
    return f"{head}... {_ELIDED_MARKER}; already acted on, do not fetch again>"


def _already_elided(content: object) -> bool:
    """Idempotent: a digest must not be digested again on the next pass."""
    return isinstance(content, str) and content.endswith(
        "already acted on, do not fetch again>"
    )


def _too_small_to_elide(content: object) -> bool:
    try:
        rendered = content if isinstance(content, str) else json.dumps(content)
    except TypeError, ValueError:
        rendered = str(content)
    return len(rendered) <= _ELIDE_MIN_CHARS


def _ordered_tool_call_ids(messages: Sequence[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        out.extend(
            part.tool_call_id for part in msg.parts if isinstance(part, ToolCallPart)
        )
    return out


def elide_consumed(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    # Replace older ``ToolReturnPart`` bodies with a stub, keeping the most
    # recent ``KEEP_RECENT_TOOL_PAIRS`` intact. Pairing is preserved
    # (Anthropic/OpenAI reject orphans); only result *content* is shortened.
    call_ids = _ordered_tool_call_ids(messages)
    if len(call_ids) <= KEEP_RECENT_TOOL_PAIRS:
        return list(messages)
    elide_ids = set(call_ids[:-KEEP_RECENT_TOOL_PAIRS])
    return [_elide_returns_in_message(msg, elide_ids) for msg in messages]


def _elide_returns_in_message(
    msg: ModelMessage,
    elide_ids: set[str],
) -> ModelMessage:
    if not isinstance(msg, ModelRequest):
        return msg
    new_parts: list[ModelRequestPart] = []
    changed = False
    for part in msg.parts:
        # A consumed return is masked whatever its type: pydantic-ai holds the
        # raw object in ``.content``, so a string-only guard would skip the
        # heaviest payloads. The stub compares equal, which keeps this idempotent.
        if (
            isinstance(part, ToolReturnPart)
            and part.tool_call_id in elide_ids
            and not part.files
            and not _already_elided(part.content)
            and not _too_small_to_elide(part.content)
        ):
            new_parts.append(
                dataclasses.replace(part, content=_digest(part.content)),
            )
            changed = True
        else:
            new_parts.append(part)
    if not changed:
        return msg
    return dataclasses.replace(msg, parts=new_parts)
