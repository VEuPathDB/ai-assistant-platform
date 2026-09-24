"""The msgpack allowlist binds at construction, so every decode enforces it."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai.ui.vercel_ai.request_types import FileUIPart, TextUIPart

from assistant_core.conversation.serde import (
    CORE_CHECKPOINT_TYPES,
    build_checkpoint_serde,
    checkpoint_types,
)


class _DeclaredState(BaseModel):
    label: str


class _UndeclaredState(BaseModel):
    label: str


def test_a_core_type_survives_a_round_trip() -> None:
    serde = build_checkpoint_serde()
    part = TextUIPart(text="hello")

    assert serde.loads_typed(serde.dumps_typed(part)) == part


def test_a_file_part_of_the_user_message_survives_a_round_trip() -> None:
    serde = build_checkpoint_serde()
    part = FileUIPart(
        media_type="image/png",
        filename="blot.png",
        url="data:image/png;base64,iVBORw0KGgotcHJvYmUtaW1hZ2U=",
    )

    assert serde.loads_typed(serde.dumps_typed(part)) == part


def test_a_declared_assistant_type_survives_a_round_trip() -> None:
    serde = build_checkpoint_serde((_DeclaredState,))
    value = _DeclaredState(label="kept")

    assert serde.loads_typed(serde.dumps_typed(value)) == value


def test_an_undeclared_type_does_not_come_back_as_itself() -> None:
    """A type on no spec is returned as its payload, never rebuilt."""
    serde = build_checkpoint_serde()

    decoded = serde.loads_typed(serde.dumps_typed(_UndeclaredState(label="lost")))

    assert not isinstance(decoded, _UndeclaredState)


def test_the_union_is_the_core_types_plus_what_the_assistants_declare() -> None:
    assert checkpoint_types((_DeclaredState,)) == (
        *CORE_CHECKPOINT_TYPES,
        _DeclaredState,
    )
