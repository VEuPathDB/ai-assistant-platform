"""What the scratchpad toolset offers, and the read streak it breaks."""

from __future__ import annotations

from typing import NoReturn
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.usage import RunUsage

from assistant_core.graph.runtime import AssistantDeps
from assistant_core.scratchpad.rendering import ScratchpadGuidance
from assistant_core.scratchpad.toolset import (
    _read_tools_to_hide,
    build_scratchpad_toolset,
    withheld_scratchpad_tools,
    withhold_scratchpad_tools,
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

    assert isinstance(toolset, FunctionToolset)
    assert sorted(toolset.tools) == TOOL_NAMES


def test_an_empty_scratchpad_withholds_every_tool_but_note() -> None:
    assert sorted(withheld_scratchpad_tools(0, [])) == [
        name for name in TOOL_NAMES if name != "note"
    ]


def test_a_scratchpad_with_notes_withholds_only_a_read_streak() -> None:
    assert withheld_scratchpad_tools(2, _calls("list_notes")) == frozenset()
    assert withheld_scratchpad_tools(2, _calls("list_notes", "list_notes")) == (
        frozenset({"list_notes"})
    )


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
    assert isinstance(toolset, FunctionToolset)
    description = toolset.tools[name].tool_def.description
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

    assert plain.startswith("Promote a note to the user's long-term memory.")
    assert "marker set" not in plain


def test_the_sentence_reaches_no_other_tool() -> None:
    guidance = ScratchpadGuidance(promote="Promote a named marker set.")

    assert _tool_description(guidance, "note") == _tool_description(
        ScratchpadGuidance(),
        "note",
    )


_TOOL_NAMES = (
    "note",
    "update_note",
    "delete_note",
    "pin_note",
    "unpin_note",
    "list_notes",
    "search_notes",
    "read_note",
    "promote_to_memory",
)


def test_the_note_tool_describes_a_note() -> None:
    assert _tool_description(ScratchpadGuidance(), "note").startswith(
        "Save a note.\n",
    )


@pytest.mark.parametrize("name", _TOOL_NAMES)
def test_no_tool_description_names_a_scratchpad_or_a_thread(name: str) -> None:
    description = _tool_description(ScratchpadGuidance(), name).lower()

    assert "scratchpad" not in description
    assert "thread" not in description


def _no_database() -> NoReturn:
    msg = "the rule read the notes of a request that carries no scratchpad tool"
    raise AssertionError(msg)


async def test_a_request_without_scratchpad_tools_reads_no_notes() -> None:
    ctx = RunContext(
        deps=AssistantDeps(
            site_id="site",
            db_session_factory=_no_database,
            conversation_id=uuid4(),
        ),
        model=TestModel(),
        usage=RunUsage(),
    )

    assert await withhold_scratchpad_tools(ctx, ["read_step_ids", "count_search"]) == (
        frozenset()
    )
