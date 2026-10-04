"""A section update that follows a tool result is not a user message, so a
scripted model reads neither a new turn nor new user words from it."""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)

from assistant_core.capabilities.stable_instructions import SECTION_UPDATE_LEAD
from assistant_core.models.scripted import current_turn, user_texts

_UPDATE: list[UserContent] = [SECTION_UPDATE_LEAD, "## Stage\nbuilt"]

_RUN: list[ModelMessage] = [
    ModelRequest(parts=[UserPromptPart(content="Find kinases")]),
    ModelResponse(parts=[ToolCallPart("classify", {}, tool_call_id="c1")]),
    ModelRequest(
        parts=[
            ToolReturnPart("classify", "ok", tool_call_id="c1"),
            UserPromptPart(content=_UPDATE),
        ]
    ),
]


def test_a_section_update_starts_no_turn() -> None:
    assert current_turn(_RUN) == _RUN


def test_a_section_update_is_no_user_text() -> None:
    assert user_texts(_RUN) == ["Find kinases"]
