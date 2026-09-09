from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

from pydantic_ai.messages import (
    BaseToolCallPart,
    BaseToolReturnPart,
    CompactionPart,
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)

from assistant_core.conversation.history.pairing import collect_ids
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

COMPACT_AT_ESTIMATED_TOKENS = 100_000
# The kept tail is sized by what it costs, because a few vocabulary reads can
# outweigh the whole middle. The floor lets a pass act on its latest result
# whatever that result costs.
KEEP_RECENT_EXCHANGE_TOKENS = COMPACT_AT_ESTIMATED_TOKENS // 2
MIN_KEEP_RECENT_EXCHANGES = 2

_DIGEST_CHAR_CAP = 4_000
_DIGEST_OPENING = (
    "Earlier steps were compacted to save context. What happened, oldest first:"
)
_DIGEST_CLOSING = (
    "The workspace state (spec draft, notes) already reflects all of this; "
    "do not redo these calls."
)
_OMITTED_MARKER = "(oldest lines omitted)"
_ARGS_HEAD_CHARS = 80
_RESULT_HEAD_CHARS = 160
_CHARS_PER_TOKEN = 4

_CONTENT_PARTS = (
    SystemPromptPart,
    UserPromptPart,
    BaseToolReturnPart,
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    CompactionPart,
)


def _render(content: object) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content)
    except TypeError, ValueError:
        return str(content)


def _flat(content: object, limit: int) -> str:
    """One digest line holds one exchange, so newlines collapse to spaces."""
    return " ".join(_render(content).split())[:limit]


def _part_chars(part: ModelRequestPart | ModelResponsePart) -> int:
    if isinstance(part, BaseToolCallPart):
        return len(part.tool_name) + len(part.args_as_json_str())
    if isinstance(part, _CONTENT_PARTS):
        return len(_render(part.content))
    return 0


def _estimated_tokens(messages: Sequence[ModelMessage]) -> int:
    chars = sum(_part_chars(part) for msg in messages for part in msg.parts)
    return chars // _CHARS_PER_TOKEN


@dataclasses.dataclass(frozen=True)
class _TailSplit:
    """Where the kept tail starts, and how many exchanges it holds."""

    start: int
    exchanges: int


def _tail_split(messages: Sequence[ModelMessage]) -> _TailSplit:
    """The newest exchanges that fit the tail budget, on a pair boundary.

    ``start`` is ``len(messages)`` when no complete pair exists. An exchange
    below ``MIN_KEEP_RECENT_EXCHANGES`` is kept whatever it costs.
    """
    exchanges = 0
    kept_tokens = 0
    start = len(messages)
    i = len(messages) - 1
    while i >= 1:
        if not (
            isinstance(messages[i], ModelRequest)
            and isinstance(messages[i - 1], ModelResponse)
        ):
            i -= 1
            continue
        # The slice holds the pair plus anything newer not counted yet, so
        # every kept message is counted exactly once.
        pair_tokens = _estimated_tokens(messages[i - 1 : start])
        over_budget = kept_tokens + pair_tokens > KEEP_RECENT_EXCHANGE_TOKENS
        if exchanges >= MIN_KEEP_RECENT_EXCHANGES and over_budget:
            break
        exchanges += 1
        kept_tokens += pair_tokens
        start = i - 1
        i -= 2
    if exchanges == 0:
        return _TailSplit(len(messages), 0)
    # A dropped middle must end on a request, so every call it holds keeps the
    # return that answers it.
    while start > 1 and isinstance(messages[start - 1], ModelResponse):
        start -= 1
    return _TailSplit(start, exchanges)


def _middle_results(middle: Sequence[ModelMessage]) -> dict[str, str]:
    out: dict[str, str] = {}
    for msg in middle:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, BaseToolReturnPart):
                out[part.tool_call_id] = _flat(part.content, _RESULT_HEAD_CHARS)
            elif isinstance(part, RetryPromptPart) and part.tool_call_id:
                head = _flat(part.content, _RESULT_HEAD_CHARS)
                out[part.tool_call_id] = f"retry: {head}"
    return out


def _user_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        return " ".join(item for item in content if isinstance(item, str))
    return ""


def _digest_lines(middle: Sequence[ModelMessage]) -> list[str]:
    results = _middle_results(middle)
    lines: list[str] = []
    for msg in middle:
        if isinstance(msg, ModelRequest):
            for req_part in msg.parts:
                if isinstance(req_part, UserPromptPart):
                    text = _user_text(req_part.content)
                    if text.strip():
                        lines.append(f"- user said: {_flat(text, _RESULT_HEAD_CHARS)}")
            continue
        for part in msg.parts:
            if isinstance(part, TextPart):
                if part.content.strip():
                    lines.append(f"- said: {_flat(part.content, _RESULT_HEAD_CHARS)}")
            elif isinstance(part, BaseToolCallPart):
                args = _flat(part.args_as_json_str(), _ARGS_HEAD_CHARS)
                result = results.get(part.tool_call_id, "(no result recorded)")
                lines.append(f"- {part.tool_name}({args}) -> {result}")
    return lines


def _assemble_digest(lines: Sequence[str], *, omitted: bool) -> str:
    opening = [_DIGEST_OPENING, _OMITTED_MARKER] if omitted else [_DIGEST_OPENING]
    return "\n".join([*opening, *lines, _DIGEST_CLOSING])


_USER_LINE_PREFIX = "- user said: "
_DIGEST_FRAMING = frozenset({_DIGEST_OPENING, _OMITTED_MARKER, _DIGEST_CLOSING})


def _digest_body(digest: str) -> list[str]:
    """The lines of a digest, without the framing that wraps them."""
    return [line for line in digest.split("\n") if line not in _DIGEST_FRAMING]


def _head_without_digests(
    head: ModelRequest,
) -> tuple[list[ModelRequestPart], list[str]]:
    """The head's own parts, and the lines of the digests it already carries.

    The head holds exactly one digest, so an earlier one is carried into the
    new digest instead of kept beside it.
    """
    kept: list[ModelRequestPart] = []
    prior: list[str] = []
    for part in head.parts:
        content = part.content if isinstance(part, UserPromptPart) else None
        if isinstance(content, str) and content.startswith(_DIGEST_OPENING):
            prior.extend(_digest_body(content))
            continue
        kept.append(part)
    return kept, prior


def _build_digest(
    middle: Sequence[ModelMessage],
    prior_lines: Sequence[str] = (),
) -> str:
    lines = [*prior_lines, *_digest_lines(middle)]
    whole = _assemble_digest(lines, omitted=False)
    if len(whole) <= _DIGEST_CHAR_CAP:
        return whole
    # Newest dropped work is the most relevant, so the cap keeps the tail.
    # A user's own words are constraints, so they survive the cap regardless
    # of age.
    budget = _DIGEST_CHAR_CAP - len(_assemble_digest((), omitted=True))
    keep = [line.startswith(_USER_LINE_PREFIX) for line in lines]
    used = sum(len(line) + 1 for line, held in zip(lines, keep, strict=True) if held)
    for i in range(len(lines) - 1, -1, -1):
        if keep[i]:
            continue
        used += len(lines[i]) + 1
        if used > budget:
            break
        keep[i] = True
    kept = [line for line, held in zip(lines, keep, strict=True) if held]
    return _assemble_digest(kept, omitted=True)


def _orphan_free(messages: Sequence[ModelMessage]) -> bool:
    call_ids, satisfied_ids, _, _ = collect_ids(messages)
    return call_ids == satisfied_ids


def _compaction_plan(
    messages: Sequence[ModelMessage],
) -> tuple[ModelRequest, _TailSplit] | None:
    """The head request and the tail split, or ``None`` to leave the history.

    The head must carry the run's prompt and the result must still end with a
    ``ModelRequest``, so a history of another shape is left alone.
    """
    if _estimated_tokens(messages) <= COMPACT_AT_ESTIMATED_TOKENS:
        return None
    head = messages[0]
    if not isinstance(head, ModelRequest):
        return None
    if not isinstance(messages[-1], ModelRequest):
        return None
    split = _tail_split(messages)
    if split.start <= 1 or split.start >= len(messages):
        return None
    return head, split


def compact_history(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    # A long dispatch grows its history until the token ceiling ends the run.
    # Past a threshold the older exchanges collapse into one digest carried by
    # the head request, keeping the wire context bounded.
    plan = _compaction_plan(messages)
    if plan is None:
        return list(messages)
    head, split = plan
    middle = messages[1 : split.start]
    head_parts, prior_lines = _head_without_digests(head)

    compacted: list[ModelMessage] = [
        dataclasses.replace(
            head,
            parts=[
                *head_parts,
                UserPromptPart(content=_build_digest(middle, prior_lines)),
            ],
        ),
        *messages[split.start :],
    ]
    if _orphan_free(messages) and not _orphan_free(compacted):
        return list(messages)

    logger.info(
        "in-run history compacted",
        input_messages=len(messages),
        output_messages=len(compacted),
        dropped_messages=len(middle),
        kept_exchanges=split.exchanges,
        input_estimated_tokens=_estimated_tokens(messages),
        output_estimated_tokens=_estimated_tokens(compacted),
    )
    return compacted
