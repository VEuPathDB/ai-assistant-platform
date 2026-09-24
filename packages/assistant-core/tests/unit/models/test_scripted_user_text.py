"""A scripted model reads the text of a user message, whatever rides beside it."""

from __future__ import annotations

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from assistant_core.models.scripted import (
    joined_user_text,
    last_user_text,
    user_texts,
)

_IMAGE = BinaryContent(data=b"\x89PNG\r\n\x1a\n-probe-image", media_type="image/png")

_THREAD: list[ModelMessage] = [
    ModelRequest(parts=[UserPromptPart(content="Find kinases")]),
    ModelResponse(parts=[TextPart(content="Found 12.")]),
    ModelRequest(
        parts=[UserPromptPart(content=[_IMAGE, "What does this blot show?"])],
    ),
]


def test_a_message_with_a_file_is_read_as_its_text() -> None:
    assert user_texts(_THREAD) == ["Find kinases", "What does this blot show?"]
    assert last_user_text(_THREAD) == "What does this blot show?"


def test_a_message_of_a_file_alone_reads_as_no_text() -> None:
    thread = [ModelRequest(parts=[UserPromptPart(content=[_IMAGE])])]

    assert user_texts(thread) == [""]
    assert joined_user_text(thread) == ""
