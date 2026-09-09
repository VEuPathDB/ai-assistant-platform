"""The in-run history compaction processor."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from assistant_core.conversation.history.compaction import (
    _DIGEST_CHAR_CAP,
    _DIGEST_OPENING,
    COMPACT_AT_ESTIMATED_TOKENS,
    KEEP_RECENT_EXCHANGE_TOKENS,
    MIN_KEEP_RECENT_EXCHANGES,
    _estimated_tokens,
    compact_history,
)

_FAT = "F" * 10_000
_HUGE = "H" * 60_000
_ENORMOUS = "E" * 400_000


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _assistant_text(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


def _call(call_id: str, name: str = "tool_x") -> ToolCallPart:
    return ToolCallPart(
        tool_name=name,
        args={"q": f"query_{call_id}"},
        tool_call_id=call_id,
    )


def _exchange(
    call_id: str,
    *,
    content: object = _FAT,
    name: str = "tool_x",
    text: str | None = None,
) -> list[ModelMessage]:
    call_parts: list[TextPart | ToolCallPart] = []
    if text is not None:
        call_parts.append(TextPart(content=text))
    call_parts.append(_call(call_id, name))
    return [
        ModelResponse(parts=list(call_parts)),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name=name,
                    content=content,
                    tool_call_id=call_id,
                ),
            ],
        ),
    ]


def _history(n: int, *, content: object = _FAT) -> list[ModelMessage]:
    out: list[ModelMessage] = [_user("bind the criteria")]
    for i in range(n):
        out.extend(_exchange(f"call_{i}", content=content))
    return out


def _call_ids(messages: list[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            out.extend(p.tool_call_id for p in msg.parts if isinstance(p, ToolCallPart))
    return out


def _return_ids(messages: list[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            out.extend(
                p.tool_call_id for p in msg.parts if isinstance(p, ToolReturnPart)
            )
    return out


def _kept_exchanges(out: list[ModelMessage]) -> int:
    """Exchanges the output keeps verbatim, for a head plus whole pairs."""
    return (len(out) - 1) // 2


def _digest_prompts(messages: list[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        out.extend(
            str(part.content)
            for part in msg.parts
            if isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and part.content.startswith(_DIGEST_OPENING)
        )
    return out


class TestBelowThreshold:
    def test_tiny_history_is_unchanged(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(content="you are FRAME")]),
            _user("hello"),
            _assistant_text("hi"),
        ]
        assert compact_history(list(msgs)) == msgs

    def test_short_tool_history_is_unchanged(self) -> None:
        msgs = _history(6, content="ok")
        assert compact_history(list(msgs)) == msgs

    def test_many_small_exchanges_stay_below_threshold(self) -> None:
        msgs = _history(60, content="counted 132 rows")
        assert _estimated_tokens(msgs) <= COMPACT_AT_ESTIMATED_TOKENS
        assert compact_history(list(msgs)) == msgs

    def test_empty_history_is_unchanged(self) -> None:
        assert compact_history([]) == []

    def test_head_that_is_not_a_request_is_unchanged(self) -> None:
        msgs: list[ModelMessage] = [_assistant_text("stray")]
        msgs.extend(_history(50)[1:])
        assert _estimated_tokens(msgs) > COMPACT_AT_ESTIMATED_TOKENS
        assert compact_history(list(msgs)) == msgs


class TestAboveThreshold:
    def test_shape_and_tail_are_preserved(self) -> None:
        msgs = _history(50)
        assert _estimated_tokens(msgs) > COMPACT_AT_ESTIMATED_TOKENS
        out = compact_history(list(msgs))

        assert isinstance(out[-1], ModelRequest)
        head = out[0]
        assert isinstance(head, ModelRequest)
        original_head = msgs[0]
        assert isinstance(original_head, ModelRequest)
        assert list(head.parts[: len(original_head.parts)]) == list(original_head.parts)
        appended = head.parts[len(original_head.parts) :]
        assert len(appended) == 1
        digest = appended[0]
        assert isinstance(digest, UserPromptPart)
        assert isinstance(digest.content, str)
        assert digest.content.startswith(_DIGEST_OPENING)

        kept = _kept_exchanges(out)
        expected_tail = [f"call_{i}" for i in range(50 - kept, 50)]
        assert _call_ids(out) == expected_tail
        assert _return_ids(out) == expected_tail
        assert out[1:] == msgs[-2 * kept :]

    def test_the_kept_tail_fits_the_tail_budget(self) -> None:
        msgs = _history(50)
        out = compact_history(list(msgs))
        assert _estimated_tokens(out[1:]) <= KEEP_RECENT_EXCHANGE_TOKENS
        assert _estimated_tokens(out) <= COMPACT_AT_ESTIMATED_TOKENS

    def test_digest_names_the_dropped_tools(self) -> None:
        msgs = _history(50)
        out = compact_history(list(msgs))
        newest_middle = 50 - _kept_exchanges(out) - 1
        digest = _digest_prompts(out)[0]
        assert "tool_x" in digest
        assert f'"query_call_{newest_middle}"' in digest
        assert "do not redo these calls" in digest

    def test_assistant_text_in_the_middle_is_summarized(self) -> None:
        msgs: list[ModelMessage] = [_user("bind the criteria")]
        for i in range(50):
            msgs.extend(_exchange(f"call_{i}", text=f"thinking about step {i}"))
        out = compact_history(list(msgs))
        newest_middle = 50 - _kept_exchanges(out) - 1
        said = [
            line
            for line in _digest_prompts(out)[0].splitlines()
            if line.startswith("- said: ")
        ]
        assert said[-1] == f"- said: thinking about step {newest_middle}"

    def test_no_orphan_tool_calls_are_created(self) -> None:
        msgs = _history(50)
        out = compact_history(list(msgs))
        assert set(_call_ids(out)) == set(_return_ids(out))

    def test_multi_call_response_keeps_pairing(self) -> None:
        msgs: list[ModelMessage] = [_user("go")]
        for i in range(40):
            msgs.append(
                ModelResponse(
                    parts=[_call(f"call_{i}_a"), _call(f"call_{i}_b")],
                ),
            )
            msgs.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="tool_x",
                            content=_FAT,
                            tool_call_id=f"call_{i}_a",
                        ),
                        ToolReturnPart(
                            tool_name="tool_x",
                            content=_FAT,
                            tool_call_id=f"call_{i}_b",
                        ),
                    ],
                ),
            )
        out = compact_history(list(msgs))
        assert set(_call_ids(out)) == set(_return_ids(out))
        assert len(_call_ids(out)) == 2 * _kept_exchanges(out)

    def test_trailing_request_after_the_last_pair_is_kept(self) -> None:
        msgs = _history(50)
        msgs.append(_user("now write the spec"))
        out = compact_history(list(msgs))
        last = out[-1]
        assert isinstance(last, ModelRequest)
        assert [p.content for p in last.parts if isinstance(p, UserPromptPart)] == [
            "now write the spec"
        ]


class TestDeterminism:
    def test_two_calls_on_the_same_input_agree(self) -> None:
        """Only the auto-stamped prompt timestamp may differ between runs."""
        msgs = _history(50)
        first = compact_history(list(msgs))
        second = compact_history(list(msgs))
        assert _digest_prompts(first) == _digest_prompts(second)
        assert first[1:] == second[1:]
        assert _call_ids(first) == _call_ids(second)

    def test_digest_carries_no_clock_reading(self) -> None:
        msgs = _history(50)
        digest = _digest_prompts(compact_history(list(msgs)))[0]
        assert "tzinfo" not in digest
        assert "timestamp" not in digest

    def test_output_is_a_fixpoint(self) -> None:
        msgs = _history(50)
        once = compact_history(list(msgs))
        twice = compact_history(list(once))
        assert twice == once
        assert len(_digest_prompts(twice)) == 1

    def test_input_list_is_not_mutated(self) -> None:
        msgs = _history(50)
        snapshot = list(msgs)
        compact_history(msgs)
        assert msgs == snapshot


class TestSerialization:
    def test_compacted_history_round_trips(self) -> None:
        msgs = _history(50)
        out = compact_history(list(msgs))
        raw = ModelMessagesTypeAdapter.dump_json(out)
        restored = ModelMessagesTypeAdapter.validate_json(raw)
        assert _digest_prompts(list(restored)) == _digest_prompts(out)
        assert _call_ids(list(restored)) == _call_ids(out)


class TestDigestCap:
    def test_digest_respects_the_char_cap(self) -> None:
        msgs = _history(400, content="R" * 2_000)
        out = compact_history(list(msgs))
        digest = _digest_prompts(out)[0]
        assert len(digest) <= _DIGEST_CHAR_CAP + 64

    def test_digest_keeps_the_newest_middle_lines(self) -> None:
        msgs = _history(400, content="R" * 2_000)
        out = compact_history(list(msgs))
        digest = _digest_prompts(out)[0]
        newest_middle = 400 - _kept_exchanges(out) - 1
        assert f'"query_call_{newest_middle}"' in digest
        assert '"query_call_0"' not in digest
        assert "oldest lines omitted" in digest


class TestStructuredReturns:
    def test_dict_content_digests_without_raising(self) -> None:
        payload = {"rows": ["a", "b"], "blob": "z" * 10_000}
        msgs = _history(50, content=payload)
        out = compact_history(list(msgs))
        digest = _digest_prompts(out)[0]
        assert "tool_x" in digest
        assert _estimated_tokens(out) < _estimated_tokens(msgs)

    def test_unserializable_content_digests_without_raising(self) -> None:
        class _Opaque:
            def __repr__(self) -> str:
                return "OPAQUE_RESULT" * 800

        msgs = _history(50, content=_Opaque())
        assert _estimated_tokens(msgs) > COMPACT_AT_ESTIMATED_TOKENS
        out = compact_history(list(msgs))
        digest = _digest_prompts(out)[0]
        assert "OPAQUE_RESULT" in digest


class TestMiddleUserText:
    """A user message dropped from the middle survives in the digest."""

    def test_a_middle_user_message_reaches_the_digest(self) -> None:
        messages: list[ModelMessage] = [_user("bind the criteria")]
        for i in range(6):
            messages.extend(_exchange(f"call_{i}", content=_HUGE))
        messages.append(_user("only recent rows"))
        for i in range(6, 12):
            messages.extend(_exchange(f"call_{i}", content=_HUGE))

        compacted = compact_history(messages)

        digests = _digest_prompts(compacted)
        assert digests, "the fixture must cross the threshold"
        assert "user said: only recent rows" in digests[0]


class TestTheTailFitsItsBudget:
    """A fixed count of fat exchanges outweighs the whole middle."""

    def test_fat_recent_exchanges_still_compact_below_the_threshold(self) -> None:
        msgs = _history(12, content=_HUGE)
        assert _estimated_tokens(msgs) > COMPACT_AT_ESTIMATED_TOKENS
        out = compact_history(list(msgs))
        assert _estimated_tokens(out) <= COMPACT_AT_ESTIMATED_TOKENS
        assert _estimated_tokens(out[1:]) <= KEEP_RECENT_EXCHANGE_TOKENS

    def test_an_oversized_newest_exchange_does_not_starve_the_tail(self) -> None:
        msgs = _history(3, content=_ENORMOUS)
        out = compact_history(list(msgs))
        assert _kept_exchanges(out) == MIN_KEEP_RECENT_EXCHANGES
        assert out[1:] == msgs[-2 * MIN_KEEP_RECENT_EXCHANGES :]

    def test_a_fat_history_compacts_to_a_fixpoint(self) -> None:
        msgs = _history(12, content=_HUGE)
        once = compact_history(list(msgs))
        assert compact_history(list(once)) == once


class TestRepeatedCompaction:
    """The head carries one digest however many times the processor runs."""

    def _grown_history(self) -> tuple[list[ModelMessage], list[ModelMessage]]:
        msgs = _history(12, content=_HUGE)
        once = compact_history(list(msgs))
        grown = list(once)
        for i in range(12, 16):
            grown.extend(_exchange(f"call_{i}", content=_HUGE))
        return once, grown

    def test_a_second_pass_leaves_one_digest_on_the_head(self) -> None:
        once, grown = self._grown_history()
        assert len(_digest_prompts(once)) == 1
        assert _estimated_tokens(grown) > COMPACT_AT_ESTIMATED_TOKENS

        twice = compact_history(grown)

        assert len(_digest_prompts(twice)) == 1

    def test_the_second_digest_keeps_the_first_middle(self) -> None:
        _, grown = self._grown_history()
        digest = _digest_prompts(compact_history(grown))[0]
        assert '"query_call_0"' in digest
        assert '"query_call_9"' in digest

    def test_a_second_pass_stays_within_the_threshold(self) -> None:
        _, grown = self._grown_history()
        twice = compact_history(grown)
        assert _estimated_tokens(twice) <= COMPACT_AT_ESTIMATED_TOKENS
