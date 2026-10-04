"""The tool-result elision history processor."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from assistant_core.conversation.history.elision import (
    _ELIDED_MARKER,
    ELIDE_BLOCK,
    KEEP_RECENT_TOOL_PAIRS,
    elide_consumed,
)

# Results at or under the size guard stay whole, so this payload is larger.
_BIG_RESULT_PAYLOAD = "BIG_RESULT_PAYLOAD " * 40

# The fewest calls whose history digests anything: the kept tail and one block.
_FIRST_BLOCK = KEEP_RECENT_TOOL_PAIRS + ELIDE_BLOCK


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _system(text: str) -> ModelRequest:
    return ModelRequest(parts=[SystemPromptPart(content=text)])


def _call(call_id: str, name: str = "tool_x") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)


def _assistant_with_call(call_id: str, name: str = "tool_x") -> ModelResponse:
    return ModelResponse(parts=[_call(call_id, name)])


def _assistant_text(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def _tool_return(
    call_id: str,
    content: str = _BIG_RESULT_PAYLOAD,
    name: str = "tool_x",
) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=name,
                content=content,
                tool_call_id=call_id,
            ),
        ],
    )


def _interleaved_tool_calls(
    n: int,
    *,
    return_content: str = _BIG_RESULT_PAYLOAD,
) -> list[ModelMessage]:
    """Build a user prompt followed by ``n`` call and return round-trips."""
    out: list[ModelMessage] = [_user("kick off")]
    for i in range(n):
        out.append(_assistant_with_call(f"call_{i}"))
        out.append(_tool_return(f"call_{i}", content=return_content))
    return out


def _returns_in_order(
    messages: list[ModelMessage],
) -> list[ToolReturnPart]:
    out: list[ToolReturnPart] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        out.extend(p for p in msg.parts if isinstance(p, ToolReturnPart))
    return out


def _calls_in_order(messages: list[ModelMessage]) -> list[ToolCallPart]:
    out: list[ToolCallPart] = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        out.extend(p for p in msg.parts if isinstance(p, ToolCallPart))
    return out


def _digested(messages: list[ModelMessage]) -> list[bool]:
    return [_ELIDED_MARKER in str(r.content) for r in _returns_in_order(messages)]


def test_no_tool_calls_at_all() -> None:
    """A text-only exchange passes through unchanged."""
    msgs: list[ModelMessage] = [
        _system("you are an assistant"),
        _user("hello"),
        _assistant_text("hi"),
    ]
    out = elide_consumed(list(msgs))
    assert out == msgs


def test_under_keep_threshold_is_no_op() -> None:
    """Every return body survives while the call count is at or below the
    keep threshold."""
    msgs = _interleaved_tool_calls(KEEP_RECENT_TOOL_PAIRS)
    out = elide_consumed(list(msgs))
    for ret in _returns_in_order(out):
        assert ret.content == _BIG_RESULT_PAYLOAD


def test_exactly_at_keep_threshold_is_no_op() -> None:
    msgs = _interleaved_tool_calls(KEEP_RECENT_TOOL_PAIRS)
    out = elide_consumed(list(msgs))
    assert out == msgs


def test_older_returns_get_stub_recent_returns_keep_payload() -> None:
    """The oldest block of return bodies becomes a stub. Every return after
    the block keeps the full payload."""
    n = _FIRST_BLOCK + 2
    msgs = _interleaved_tool_calls(n)
    out = elide_consumed(list(msgs))
    returns = _returns_in_order(out)
    assert len(returns) == n
    elided = returns[:ELIDE_BLOCK]
    kept = returns[ELIDE_BLOCK:]
    assert all(r.content != _BIG_RESULT_PAYLOAD for r in elided)
    assert all("elided" in str(r.content).lower() for r in elided)
    assert all(r.content == _BIG_RESULT_PAYLOAD for r in kept)
    assert len(kept) == KEEP_RECENT_TOOL_PAIRS + 2


def test_pairing_is_preserved() -> None:
    """Each tool call keeps a matching return with the same tool_call_id.
    Elision changes the result body only."""
    n = _FIRST_BLOCK + 7
    msgs = _interleaved_tool_calls(n)
    out = elide_consumed(list(msgs))
    call_ids = [c.tool_call_id for c in _calls_in_order(out)]
    return_ids = [r.tool_call_id for r in _returns_in_order(out)]
    assert call_ids == [f"call_{i}" for i in range(n)]
    assert return_ids == call_ids


def test_tool_call_args_are_not_touched() -> None:
    """Call arguments stay intact. Only result bodies get the stub."""
    n = _FIRST_BLOCK + 3
    msgs: list[ModelMessage] = [_user("go")]
    for i in range(n):
        call = ToolCallPart(
            tool_name="search",
            args={"q": f"query_{i}", "context": "important_args"},
            tool_call_id=f"call_{i}",
        )
        msgs.append(ModelResponse(parts=[call]))
        msgs.append(_tool_return(f"call_{i}"))
    out = elide_consumed(list(msgs))
    assert sum(_digested(out)) == ELIDE_BLOCK
    assert [call.args for call in _calls_in_order(out)] == [
        {"q": f"query_{i}", "context": "important_args"} for i in range(n)
    ]


def test_user_and_system_messages_untouched() -> None:
    """System and user prompt parts stay unchanged."""
    msgs: list[ModelMessage] = [
        _system("scoped to the workspace"),
        _user("find matching rows"),
    ]
    msgs.extend(_interleaved_tool_calls(_FIRST_BLOCK + 2)[1:])
    msgs.append(_user("follow-up question"))
    out = elide_consumed(list(msgs))
    sys_prompts: list[SystemPromptPart] = []
    user_prompts: list[UserPromptPart] = []
    for msg in out:
        if isinstance(msg, ModelRequest):
            sys_prompts.extend(p for p in msg.parts if isinstance(p, SystemPromptPart))
            user_prompts.extend(p for p in msg.parts if isinstance(p, UserPromptPart))
    assert [p.content for p in sys_prompts] == ["scoped to the workspace"]
    user_contents = [p.content for p in user_prompts]
    assert "find matching rows" in user_contents
    assert "follow-up question" in user_contents


def test_retry_prompt_parts_untouched() -> None:
    """Retry prompt parts carry error feedback and stay verbatim."""
    retry = RetryPromptPart(
        content="invalid arguments, try again",
        tool_call_id="call_0",
        tool_name="tool_x",
    )
    msgs: list[ModelMessage] = [_user("go")]
    for i in range(_FIRST_BLOCK + 2):
        msgs.append(_assistant_with_call(f"call_{i}"))
        msgs.append(
            ModelRequest(
                parts=[
                    retry
                    if i == 0
                    else ToolReturnPart(
                        tool_name="tool_x",
                        content="OK",
                        tool_call_id=f"call_{i}",
                    ),
                ],
            ),
        )
    out = elide_consumed(list(msgs))
    found_retry = False
    for msg in out:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, RetryPromptPart):
                assert part.content == "invalid arguments, try again"
                found_retry = True
    assert found_retry


def test_idempotent_when_already_elided() -> None:
    """The processor runs before every model request, so a second pass over
    the same history is a no-op."""
    msgs = _interleaved_tool_calls(_FIRST_BLOCK + 4)
    once = elide_consumed(list(msgs))
    twice = elide_consumed(once)
    assert once != msgs
    assert once == twice


def test_text_only_assistant_responses_not_dropped() -> None:
    """Assistant text parts pass through unchanged."""
    msgs: list[ModelMessage] = [_user("go")]
    for i in range(_FIRST_BLOCK + 1):
        msgs.append(
            ModelResponse(
                parts=[
                    TextPart(content=f"thinking step {i}"),
                    _call(f"call_{i}"),
                ],
            ),
        )
        msgs.append(_tool_return(f"call_{i}"))
    out = elide_consumed(list(msgs))
    text_contents: list[str] = []
    for msg in out:
        if not isinstance(msg, ModelResponse):
            continue
        text_contents.extend(p.content for p in msg.parts if isinstance(p, TextPart))
    expected = [f"thinking step {i}" for i in range(_FIRST_BLOCK + 1)]
    assert text_contents == expected


# Tool returns hold Pydantic models, lists, or dicts. pydantic-ai keeps the raw
# object in ToolReturnPart.content and serializes it only at request-build time.


class _StructuredResult(BaseModel):
    query_name: str
    rows: list[str]


def _structured_tool_return(call_id: str, content: object) -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="tool_x",
                content=content,
                tool_call_id=call_id,
            ),
        ],
    )


def _interleaved_structured(
    n: int,
    *,
    payload: object,
) -> list[ModelMessage]:
    out: list[ModelMessage] = [_user("kick off")]
    for i in range(n):
        out.append(_assistant_with_call(f"call_{i}"))
        out.append(_structured_tool_return(f"call_{i}", payload))
    return out


def test_older_structured_dict_returns_get_stubbed() -> None:
    """A dict tool return is masked once consumed."""
    payload = {"results": ["a", "b", "c"], "score": 0.91, "blob": "z" * 3000}
    n = _FIRST_BLOCK + 5
    msgs = _interleaved_structured(n, payload=payload)
    out = elide_consumed(list(msgs))
    returns = _returns_in_order(out)
    elided = returns[:ELIDE_BLOCK]
    kept = returns[ELIDE_BLOCK:]
    assert all(
        isinstance(r.content, str) and _ELIDED_MARKER in r.content for r in elided
    )
    assert all(r.content == payload for r in kept)
    assert len(kept) == KEEP_RECENT_TOOL_PAIRS + 5


def test_older_structured_list_returns_get_stubbed() -> None:
    """A list tool return collapses to the stub once consumed."""
    payload = [{"name": f"Query{i}", "description": "d" * 500} for i in range(8)]
    n = _FIRST_BLOCK + 4
    msgs = _interleaved_structured(n, payload=payload)
    out = elide_consumed(list(msgs))
    assert _digested(out) == [True] * ELIDE_BLOCK + [False] * (n - ELIDE_BLOCK)


def test_older_pydantic_model_returns_get_stubbed() -> None:
    """A Pydantic model tool return is masked once consumed."""
    payload = _StructuredResult(query_name="QueryByText", rows=["r"] * 200)
    n = _FIRST_BLOCK + 3
    msgs = _interleaved_structured(n, payload=payload)
    out = elide_consumed(list(msgs))
    returns = _returns_in_order(out)
    elided = returns[:ELIDE_BLOCK]
    kept = returns[ELIDE_BLOCK:]
    assert [_ELIDED_MARKER in str(r.content) for r in elided] == [True] * ELIDE_BLOCK
    assert [r.content for r in kept] == [payload] * (n - ELIDE_BLOCK)


def test_structured_elision_is_idempotent() -> None:
    """A second pass leaves an already stubbed structured return alone."""
    payload = {"big": "y" * 4000}
    msgs = _interleaved_structured(_FIRST_BLOCK + 4, payload=payload)
    once = elide_consumed(list(msgs))
    twice = elide_consumed(once)
    assert once != msgs
    assert once == twice


def test_a_long_tool_call_loop_collapses_payload() -> None:
    """A long tool-call loop digests whole blocks and keeps the full payload
    only on the returns after the last block."""
    big = "X" * 3000
    n = KEEP_RECENT_TOOL_PAIRS + 3 * ELIDE_BLOCK + 3
    msgs = _interleaved_tool_calls(n, return_content=big)
    out = elide_consumed(list(msgs))
    returns = _returns_in_order(out)
    full_count = sum(1 for r in returns if r.content == big)
    assert full_count == KEEP_RECENT_TOOL_PAIRS + 3
    elided_bytes = sum(
        len(big) - len(str(r.content)) for r in returns if r.content != big
    )
    assert elided_bytes > 50_000


def _call_and_return(tool: str, tcid: str, result: object) -> list[ModelMessage]:
    return [
        ModelResponse(parts=[ToolCallPart(tool_name=tool, args={}, tool_call_id=tcid)]),
        ModelRequest(
            parts=[ToolReturnPart(tool_name=tool, content=result, tool_call_id=tcid)]
        ),
    ]


def _returned_contents(messages: list[ModelMessage]) -> list[object]:
    return [part.content for part in _returns_in_order(messages)]


class TestElisionDoesNotCauseRefetching:
    """Eliding a result the agent still needs makes it call the tool again."""

    def _history(self, results: list[object]) -> list[ModelMessage]:
        history: list[ModelMessage] = [_user("find rows")]
        for i, result in enumerate(results):
            history.extend(_call_and_return(f"tool_{i}", f"call_{i}", result))
        return history

    def test_a_small_result_is_never_elided(self) -> None:
        results: list[object] = [326] * (_FIRST_BLOCK + 3)

        kept = _returned_contents(elide_consumed(self._history(results)))

        assert kept == results

    def test_a_bulky_result_is_still_compressed(self) -> None:
        bulky = {"records": [{"id": f"PF3D7_{i:06d}"} for i in range(500)]}
        results: list[object] = [bulky] * (_FIRST_BLOCK + 2)

        kept = _returned_contents(elide_consumed(self._history(results)))
        compressed = [k for k in kept if isinstance(k, str) and "elided" in k]

        assert len(compressed) == ELIDE_BLOCK, "large payloads must still be compressed"

    def test_a_compressed_result_keeps_a_usable_digest(self) -> None:
        bulky = {"estimatedSize": 326, "records": [{"id": f"g{i}"} for i in range(500)]}
        results: list[object] = [bulky] * (_FIRST_BLOCK + 2)

        kept = _returned_contents(elide_consumed(self._history(results)))
        compressed = [k for k in kept if isinstance(k, str) and "elided" in k]

        assert compressed, "expected at least one compressed result"
        assert "326" in compressed[0], (
            "the digest must carry the facts the agent would otherwise re-fetch"
        )

    def test_the_digest_does_not_invite_a_re_call(self) -> None:
        bulky = {"records": [{"id": f"g{i}"} for i in range(500)]}
        results: list[object] = [bulky] * (_FIRST_BLOCK + 2)

        kept = _returned_contents(elide_consumed(self._history(results)))
        compressed = [k for k in kept if isinstance(k, str) and "elided" in k]

        assert compressed
        assert "re-call" not in compressed[0].lower()

    def test_recent_results_are_untouched(self) -> None:
        bulky = {"records": [{"id": f"g{i}"} for i in range(500)]}
        results: list[object] = [bulky] * (_FIRST_BLOCK + 2)

        kept = _returned_contents(elide_consumed(self._history(results)))

        assert kept[-KEEP_RECENT_TOOL_PAIRS:] == results[-KEEP_RECENT_TOOL_PAIRS:]


def _first_calls(history: list[ModelMessage], calls: int) -> list[ModelMessage]:
    """The history a run holds after ``calls`` call and return round-trips."""
    return history[: 1 + 2 * calls]


def _is_block_edge(calls: int) -> bool:
    past_tail = calls - KEEP_RECENT_TOOL_PAIRS
    return past_tail >= ELIDE_BLOCK and past_tail % ELIDE_BLOCK == 0


_LONG_RUN = KEEP_RECENT_TOOL_PAIRS + 3 * ELIDE_BLOCK


class TestElisionGrowsInBlocks:
    """A run's requests stay append-only between two block edges."""

    def test_requests_between_block_edges_extend_each_other_exactly(self) -> None:
        history = _interleaved_tool_calls(_LONG_RUN)
        extended = 0
        for calls in range(_LONG_RUN):
            if _is_block_edge(calls + 1):
                continue
            before = elide_consumed(_first_calls(history, calls))
            after = elide_consumed(_first_calls(history, calls + 1))
            assert len(after) == len(before) + 2
            for index, message in enumerate(before):
                assert after[index] == message, (calls, index)
            extended += 1
        assert extended == _LONG_RUN - 3

    @pytest.mark.parametrize("blocks", [1, 2, 3])
    def test_a_block_edge_digests_exactly_one_more_block(self, blocks: int) -> None:
        edge = KEEP_RECENT_TOOL_PAIRS + blocks * ELIDE_BLOCK
        history = _interleaved_tool_calls(edge)

        before = _digested(elide_consumed(_first_calls(history, edge - 1)))
        after = _digested(elide_consumed(history))

        assert sum(after) - sum(before) == ELIDE_BLOCK
        assert (
            after == [True] * (blocks * ELIDE_BLOCK) + [False] * KEEP_RECENT_TOOL_PAIRS
        )

    def test_the_most_recent_returns_are_never_digested(self) -> None:
        history = _interleaved_tool_calls(_LONG_RUN)
        for calls in range(1, _LONG_RUN + 1):
            flags = _digested(elide_consumed(_first_calls(history, calls)))
            recent = min(calls, KEEP_RECENT_TOOL_PAIRS)
            assert flags[-KEEP_RECENT_TOOL_PAIRS:] == [False] * recent, calls

    def test_a_second_pass_changes_nothing_at_any_count(self) -> None:
        history = _interleaved_tool_calls(_LONG_RUN)
        for calls in range(_LONG_RUN + 1):
            once = elide_consumed(_first_calls(history, calls))
            assert elide_consumed(once) == once, calls

    def test_fewer_calls_than_the_tail_and_one_block_digest_nothing(self) -> None:
        history = _interleaved_tool_calls(_FIRST_BLOCK - 1)
        for calls in range(_FIRST_BLOCK):
            prefix = _first_calls(history, calls)
            assert elide_consumed(prefix) == prefix, calls
