"""What the scratchpad toolset offers, and the read streak it breaks."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.toolsets.prepared import PreparedToolset

from assistant_core.scratchpad.rendering import ScratchpadGuidance
from assistant_core.scratchpad.toolset import (
    _read_tools_to_hide,
    build_scratchpad_toolset,
)

PROMOTED_KIND = "knowledge"

TOOL_NAMES = [
    "delete_note",
    "list_notes",
    "note",
    "pin_note",
    "promote_to_memory",
    "read_note",
    "search_notes",
    "unpin_note",
    "update_note",
]


def _calls(*names: str) -> list[ModelMessage]:
    return [ModelResponse(parts=[ToolCallPart(tool_name=name)]) for name in names]


def test_the_toolset_carries_the_nine_scratchpad_tools() -> None:
    toolset = build_scratchpad_toolset(promoted_kind=PROMOTED_KIND)

    assert isinstance(toolset, PreparedToolset)
    inner = toolset.wrapped
    assert isinstance(inner, FunctionToolset)
    assert sorted(inner.tools) == TOOL_NAMES


def test_no_read_tool_is_hidden_before_the_streak_is_reached() -> None:
    assert _read_tools_to_hide(_calls("list_notes")) == frozenset()


def test_a_read_tool_called_twice_in_a_row_is_hidden() -> None:
    assert _read_tools_to_hide(_calls("list_notes", "list_notes")) == frozenset(
        {"list_notes"},
    )


def test_two_read_tools_each_called_twice_are_both_hidden() -> None:
    history = _calls("search_notes", "list_notes", "search_notes", "list_notes")

    assert _read_tools_to_hide(history) == frozenset({"list_notes", "search_notes"})


def test_a_later_write_ends_the_streak() -> None:
    history = _calls("list_notes", "list_notes", "note")

    assert _read_tools_to_hide(history) == frozenset()


def test_a_message_that_calls_nothing_leaves_the_streak_alone() -> None:
    history: list[ModelMessage] = [
        ModelResponse(parts=[ToolCallPart(tool_name="list_notes")]),
        ModelResponse(parts=[TextPart(content="thinking")]),
        ModelResponse(parts=[ToolCallPart(tool_name="list_notes")]),
    ]

    assert _read_tools_to_hide(history) == frozenset({"list_notes"})


def _tool_description(guidance: ScratchpadGuidance, name: str) -> str:
    toolset = build_scratchpad_toolset(
        guidance=guidance,
        promoted_kind=PROMOTED_KIND,
    )
    inner = toolset.wrapped
    assert isinstance(inner, FunctionToolset)
    description = inner.tools[name].tool_def.description
    assert description is not None
    return description


def test_the_hosts_sentence_is_appended_to_the_promote_tool_description() -> None:
    plain = _tool_description(ScratchpadGuidance(), "promote_to_memory")

    coached = _tool_description(
        ScratchpadGuidance(promote="Promote a named marker set, not a step count."),
        "promote_to_memory",
    )

    assert coached == f"{plain}\n\nPromote a named marker set, not a step count."


def test_a_host_that_supplies_no_sentence_gets_the_tool_docstring_alone() -> None:
    plain = _tool_description(ScratchpadGuidance(), "promote_to_memory")

    assert plain.startswith(
        "Promote a scratchpad note to the user's long-term memory.",
    )
    assert "marker set" not in plain


def test_the_sentence_reaches_no_other_tool() -> None:
    guidance = ScratchpadGuidance(promote="Promote a named marker set.")

    assert _tool_description(guidance, "note") == _tool_description(
        ScratchpadGuidance(),
        "note",
    )
