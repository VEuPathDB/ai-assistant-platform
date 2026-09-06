"""PROTOCOL.md describes the wire this runtime actually emits.

Every example in the document is captured from a real turn here and compared
byte for byte, and every kind the document names is checked against the code
that defines it. A protocol change that skips the document fails this suite.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai.ui.vercel_ai import response_types
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk
from tests.sse import DONE_PAYLOAD, read_stream
from tests.synthetic import (
    ADD_PROMPT,
    APPROVAL_PROMPT,
    LOOP_PROMPT,
    PLAIN_PROMPT,
    STOP_PROMPT,
    SyntheticRuntime,
)

from assistant_core.conversation.stream_parts.core_parts import (
    register_core_stream_parts,
)
from assistant_core.conversation.stream_parts.registry import StreamPartRegistry
from assistant_core.conversation.ui_message_reducer import (
    ASSISTANT_MESSAGE_CHUNK_TYPE,
    SYSTEM_MESSAGE_CHUNK_TYPE,
    USER_MESSAGE_CHUNK_TYPE,
)

PROTOCOL = Path(__file__).parents[4] / "PROTOCOL.md"

_EXAMPLES_BLOCK = re.compile(
    r"<!-- examples:begin -->\n(.*?)\n<!-- examples:end -->",
    re.DOTALL,
)
_EXAMPLE = re.compile(r"#### `([^`]+)`\n\n```json\n(.*?)\n```", re.DOTALL)
_TABLE_KIND = re.compile(r"^\| `([a-z][a-z0-9-]*)` \|", re.MULTILINE)
_SECTION = re.compile(r"<!-- (\w+):begin -->\n(.*?)\n<!-- \1:end -->", re.DOTALL)

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_FIXED_INSTANT = "2026-01-01T00:00:00Z"


def _placeholder(value: str) -> str:
    """A generated identifier or instant reads as its placeholder."""
    try:
        UUID(value)
    except ValueError:
        pass
    else:
        return _ZERO_UUID
    if "T" not in value:
        return value
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return value
    return _FIXED_INSTANT


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, str):
        return _placeholder(value)
    return value


def _section(name: str) -> str:
    for found in _SECTION.finditer(PROTOCOL.read_text()):
        if found.group(1) == name:
            return found.group(2)
    msg = f"PROTOCOL.md has no <!-- {name}:begin --> section"
    raise AssertionError(msg)


def _documented_examples() -> dict[str, str]:
    block = _EXAMPLES_BLOCK.search(PROTOCOL.read_text())
    assert block is not None, "PROTOCOL.md has no captured-examples block"
    return dict(_EXAMPLE.findall(block.group(1)))


def _render(chunk: dict[str, Any]) -> str:
    return json.dumps(_canonical(chunk), indent=2)


@pytest.fixture
async def captured(runtime: SyntheticRuntime) -> dict[str, str]:
    """One example per chunk kind the reference assistant can produce.

    Each turn is read as its own stream, because a reader stops at the
    terminator of the turn it attached to.
    """
    prompts = (PLAIN_PROMPT, ADD_PROMPT, APPROVAL_PROMPT, LOOP_PROMPT, STOP_PROMPT)
    examples: dict[str, str] = {}
    cursor = 0
    for prompt in prompts:
        await runtime.run(prompt)
        frames = await read_stream(runtime.conversation_id, after=cursor)
        for frame in frames:
            if frame.is_done:
                examples.setdefault("done", f'"{DONE_PAYLOAD}"')
                continue
            chunk = frame.chunk()
            examples.setdefault(str(chunk["type"]), _render(chunk))
        last_id = frames[-1].event_id
        assert last_id is not None
        cursor = last_id
    return examples


def test_the_document_names_every_chunk_kind_the_wire_carries(
    captured: dict[str, str],
) -> None:
    assert set(_documented_examples()) == set(captured)


def test_every_documented_example_is_the_frame_the_runtime_emitted(
    captured: dict[str, str],
) -> None:
    documented = _documented_examples()

    drifted = {
        kind: (documented[kind], body)
        for kind, body in captured.items()
        if kind in documented and documented[kind] != body
    }

    assert drifted == {}


def test_the_data_part_table_lists_the_parts_the_runtime_registers() -> None:
    registry = StreamPartRegistry()
    register_core_stream_parts(registry)

    assert set(_TABLE_KIND.findall(_section("data_parts"))) == registry.kinds()


def _chunk_kinds() -> set[str]:
    """Every kind a chunk class in the SDK pins with a literal default.

    A class whose ``type`` is an argument rather than a default carries a
    family of kinds, and the data-part table names those.
    """
    kinds: set[str] = set()
    for name in dir(response_types):
        candidate = getattr(response_types, name)
        if not isinstance(candidate, type) or not issubclass(candidate, BaseChunk):
            continue
        field = candidate.model_fields.get("type")
        if field is not None and isinstance(field.default, str):
            kinds.add(field.default)
    return kinds


def test_the_chunk_table_lists_the_chunk_kinds_the_sdk_defines() -> None:
    assert set(_TABLE_KIND.findall(_section("chunks"))) == _chunk_kinds()


_DECLARED_VERSION = re.compile(r"^\*\*Version (\d+\.\d+\.\d+)\.\*\*", re.MULTILINE)
_CHANGELOG_VERSION = re.compile(r"^\| `(\d+\.\d+\.\d+)` \|", re.MULTILINE)


def test_the_changelog_names_the_version_the_document_declares() -> None:
    declared = _DECLARED_VERSION.search(PROTOCOL.read_text())
    assert declared is not None, "PROTOCOL.md declares no version"

    assert declared.group(1) in set(
        _CHANGELOG_VERSION.findall(_section("changelog")),
    )


def test_the_envelope_table_lists_the_kinds_the_log_holds_but_never_frames() -> None:
    assert set(_TABLE_KIND.findall(_section("envelopes"))) == {
        USER_MESSAGE_CHUNK_TYPE,
        SYSTEM_MESSAGE_CHUNK_TYPE,
        ASSISTANT_MESSAGE_CHUNK_TYPE,
    }
