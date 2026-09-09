"""The tool-call pairing history processor."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from assistant_core.conversation.history.pairing import collect_ids, pair_orphans


def _user(text: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _assistant(
    *parts: TextPart | ToolCallPart,
) -> ModelResponse:
    return ModelResponse(parts=list(parts))


def _tool_return(call_id: str, name: str = "foo") -> ModelRequest:
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=name,
                content="ok",
                tool_call_id=call_id,
            ),
        ],
    )


def _tool_call(call_id: str, name: str = "foo") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)


class TestPairToolCalls:
    def test_clean_history_passes_through_unchanged(self) -> None:
        existing = [_user("hi")]
        new = [_assistant(TextPart(content="hello"))]
        result = pair_orphans(existing + new)
        assert result == existing + new

    def test_paired_tool_call_and_return_preserved(self) -> None:
        existing = [_user("hi"), _assistant(_tool_call("c1"))]
        new = [_tool_return("c1"), _assistant(TextPart(content="done"))]
        result = pair_orphans(existing + new)
        assert len(result) == 4
        assert any(
            isinstance(p, ToolReturnPart) and p.tool_call_id == "c1"
            for m in result
            for p in m.parts
        )

    def test_orphan_tool_return_is_dropped(self) -> None:
        """A ToolReturnPart with no matching ToolCallPart is stripped."""
        existing = [_user("hi")]
        new = [_tool_return("phantom")]  # no preceding ToolCallPart
        result = pair_orphans(existing + new)
        assert result == existing  # entire orphan-return ModelRequest dropped

    def test_orphan_tool_call_gets_placeholder_return(self) -> None:
        """A ToolCallPart with no matching ToolReturnPart gets a placeholder."""
        existing = [_user("hi"), _assistant(_tool_call("c1"))]
        new: list = []  # no return for c1
        result = pair_orphans(existing + new)
        assert len(result) == 3
        last = result[-1]
        assert isinstance(last, ModelRequest)
        assert len(last.parts) == 1
        placeholder = last.parts[0]
        assert isinstance(placeholder, ToolReturnPart)
        assert placeholder.tool_call_id == "c1"
        assert isinstance(placeholder.content, str)
        assert "not executed" in placeholder.content.lower()

    def test_orphan_call_placeholder_inserted_into_next_request(self) -> None:
        """Placeholder is injected into the next ModelRequest when one exists."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
        ]
        # A later user turn lands with no tool return for c1.
        new = [_user("follow-up")]
        result = pair_orphans(existing + new)
        follow_up = result[2]
        assert isinstance(follow_up, ModelRequest)
        kinds = [type(p).__name__ for p in follow_up.parts]
        assert "ToolReturnPart" in kinds
        assert "UserPromptPart" in kinds

    def test_orphan_call_placeholder_precedes_user_prompt_in_request(
        self,
    ) -> None:
        existing = [_user("hi"), _assistant(_tool_call("c1"))]
        new = [_user("follow-up")]
        result = pair_orphans(existing + new)
        follow_up = result[2]
        assert isinstance(follow_up, ModelRequest)
        tool_return_idx = next(
            (i for i, p in enumerate(follow_up.parts) if isinstance(p, ToolReturnPart)),
            None,
        )
        user_prompt_idx = next(
            (i for i, p in enumerate(follow_up.parts) if isinstance(p, UserPromptPart)),
            None,
        )
        assert tool_return_idx is not None
        assert user_prompt_idx is not None
        assert tool_return_idx < user_prompt_idx, (
            "ToolReturnPart must precede UserPromptPart; got parts "
            f"{[type(p).__name__ for p in follow_up.parts]}"
        )

    def test_orphan_call_placeholder_precedes_system_and_user_prompts(
        self,
    ) -> None:
        existing = [_user("hi"), _assistant(_tool_call("c1"))]
        new = [
            ModelRequest(
                parts=[
                    SystemPromptPart(content="be concise"),
                    UserPromptPart(content="follow-up"),
                ],
            ),
        ]
        result = pair_orphans(existing + new)
        follow_up = result[2]
        assert isinstance(follow_up, ModelRequest)
        first = follow_up.parts[0]
        assert isinstance(first, ToolReturnPart)
        assert first.tool_call_id == "c1"

    def test_orphan_call_with_intervening_response_inserts_new_request(
        self,
    ) -> None:
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
            _assistant(TextPart(content="still talking")),
            _user("follow-up"),
        ]
        result = pair_orphans([*existing])
        inserted = result[2]
        assert isinstance(inserted, ModelRequest)
        first = inserted.parts[0]
        assert isinstance(first, ToolReturnPart)
        assert first.tool_call_id == "c1"
        assert isinstance(result[3], ModelResponse)
        assert isinstance(result[4], ModelRequest)

    def test_mixed_orphans_both_fixed(self) -> None:
        """Simultaneously drop orphan returns and pair orphan calls."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("paired")),
            _tool_return("paired"),
            _assistant(_tool_call("lonely")),  # never answered
        ]
        new = [_tool_return("ghost")]  # matches no call
        result = pair_orphans(existing + new)
        call_ids = {
            p.tool_call_id
            for m in result
            for p in m.parts
            if isinstance(p, ToolCallPart)
        }
        return_ids = {
            p.tool_call_id
            for m in result
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        }
        assert call_ids == return_ids  # every call paired, no orphan returns
        assert "ghost" not in return_ids
        assert "lonely" in return_ids  # placeholder added

    def test_partial_orphan_return_leaves_other_parts_intact(self) -> None:
        """Dropping an orphan return doesn't remove co-located parts."""
        # A ModelRequest can carry a user prompt AND a tool return together.
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
        ]
        mixed_request = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="ghost",
                    content="x",
                    tool_call_id="ghost",
                ),
                UserPromptPart(content="hello again"),
            ],
        )
        new = [mixed_request]
        result = pair_orphans(existing + new)
        survivors = result[-1]
        assert isinstance(survivors, ModelRequest)
        part_types = [type(p).__name__ for p in survivors.parts]
        assert "UserPromptPart" in part_types
        return_ids = {
            p.tool_call_id for p in survivors.parts if isinstance(p, ToolReturnPart)
        }
        assert "ghost" not in return_ids
        assert "c1" in return_ids

    def test_empty_inputs_return_empty(self) -> None:
        assert pair_orphans([]) == []

    def test_duplicate_returns_same_request_deduped(self) -> None:
        """Two ToolReturnParts with the same call_id in one request keep one."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="foo",
                        content="first",
                        tool_call_id="c1",
                    ),
                    ToolReturnPart(
                        tool_name="foo",
                        content="second",
                        tool_call_id="c1",
                    ),
                ],
            ),
        ]
        result = pair_orphans(existing)
        returns = [
            p
            for m in result
            for p in m.parts
            if isinstance(p, ToolReturnPart) and p.tool_call_id == "c1"
        ]
        assert len(returns) == 1
        # First occurrence wins.
        assert returns[0].content == "first"

    def test_duplicate_returns_across_requests_deduped(self) -> None:
        """Duplicate returns spread across separate ModelRequests collapse to one."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
            _tool_return("c1"),
            _assistant(TextPart(content="mid")),
            _tool_return("c1"),  # duplicate, later turn
        ]
        result = pair_orphans(existing)
        returns = [
            p
            for m in result
            for p in m.parts
            if isinstance(p, ToolReturnPart) and p.tool_call_id == "c1"
        ]
        assert len(returns) == 1

    def test_duplicate_returns_preserve_co_located_parts(self) -> None:
        """Deduping a return doesn't strip other parts in the same request."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
            _tool_return("c1"),
            _assistant(TextPart(content="mid")),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="foo",
                        content="dup",
                        tool_call_id="c1",
                    ),
                    UserPromptPart(content="new question"),
                ],
            ),
        ]
        result = pair_orphans(existing)
        last = result[-1]
        assert isinstance(last, ModelRequest)
        part_types = [type(p).__name__ for p in last.parts]
        # Duplicate return stripped, user prompt kept.
        assert "ToolReturnPart" not in part_types
        assert "UserPromptPart" in part_types

    def test_duplicate_returns_with_distinct_call_ids_all_kept(self) -> None:
        """Deduping is per call id, so distinct ids do not collide."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1"), _tool_call("c2"), _tool_call("c3")),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="foo",
                        content="a",
                        tool_call_id="c1",
                    ),
                    ToolReturnPart(
                        tool_name="foo",
                        content="b",
                        tool_call_id="c2",
                    ),
                    ToolReturnPart(
                        tool_name="foo",
                        content="c",
                        tool_call_id="c3",
                    ),
                ],
            ),
        ]
        result = pair_orphans(existing)
        return_ids = [
            p.tool_call_id
            for m in result
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        assert sorted(return_ids) == ["c1", "c2", "c3"]

    def test_empty_request_after_dedup_is_dropped(self) -> None:
        """A ModelRequest that only held duplicate returns is removed entirely."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("c1")),
            _tool_return("c1"),
            _tool_return("c1"),  # sole part of its own request; fully duplicate
        ]
        result = pair_orphans(existing)
        assert len(result) == 3

    def test_duplicate_tool_calls_surface_incollect_ids(self) -> None:
        """Two ToolCallParts sharing a tool_call_id flips ``has_duplicate_calls``."""
        messages = [
            _user("hi"),
            _assistant(_tool_call("dup"), _tool_call("dup")),
            _tool_return("dup"),
        ]
        (
            call_ids,
            satisfied_ids,
            has_duplicate_returns,
            has_duplicate_calls,
        ) = collect_ids(messages)
        assert call_ids == {"dup"}
        assert satisfied_ids == {"dup"}
        assert has_duplicate_returns is False
        assert has_duplicate_calls is True

    def test_duplicate_tool_calls_pass_through_without_crashing(self) -> None:
        """Duplicate call ids pass through with the message flow intact."""
        existing = [
            _user("hi"),
            _assistant(_tool_call("dup"), _tool_call("dup")),
            _tool_return("dup"),
        ]
        result = pair_orphans(existing)
        call_ids = [
            p.tool_call_id
            for m in result
            for p in m.parts
            if isinstance(p, ToolCallPart)
        ]
        return_ids = [
            p.tool_call_id
            for m in result
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        ]
        assert call_ids == ["dup", "dup"]
        assert return_ids == ["dup"]

    def test_no_duplicate_calls_or_returns_in_clean_history(self) -> None:
        """Distinct ids never trigger either duplicate flag."""
        messages = [
            _user("hi"),
            _assistant(_tool_call("c1"), _tool_call("c2")),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="foo",
                        content="a",
                        tool_call_id="c1",
                    ),
                    ToolReturnPart(
                        tool_name="foo",
                        content="b",
                        tool_call_id="c2",
                    ),
                ],
            ),
        ]
        _, _, has_dup_returns, has_dup_calls = collect_ids(messages)
        assert has_dup_returns is False
        assert has_dup_calls is False
