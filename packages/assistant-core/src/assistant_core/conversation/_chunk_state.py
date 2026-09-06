from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

Part = dict[str, Any]
Chunk = dict[str, Any]


@dataclass
class _PartialToolCall:
    text: str
    tool_name: str
    index: int
    dynamic: bool
    title: str | None


@dataclass
class _State:
    message: dict[str, Any]
    active_text_parts: dict[str, Part] = field(default_factory=dict)
    active_reasoning_parts: dict[str, Part] = field(default_factory=dict)
    partial_tool_calls: dict[str, _PartialToolCall] = field(default_factory=dict)
    finish_reason: str | None = None


@dataclass
class _ToolUpdate:
    tool_call_id: str
    tool_name: str
    state_value: str
    dynamic: bool = False
    title: str | None = None
    input_value: Any = None
    output: Any = None
    raw_input: Any = None
    error_text: str | None = None
    provider_executed: bool | None = None
    preliminary: bool | None = None
    provider_metadata: dict[str, Any] | None = None


def _new_state(message_id: str) -> _State:
    return _State(
        message={"id": message_id, "role": "assistant", "parts": []},
    )


def _is_tool_part(part: Part) -> bool:
    t = part.get("type")
    return isinstance(t, str) and (t.startswith("tool-") or t == "dynamic-tool")


def _is_static_tool_part(part: Part) -> bool:
    t = part.get("type")
    return isinstance(t, str) and t.startswith("tool-") and t != "dynamic-tool"


def _merge_metadata(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if incoming is None:
        return existing
    if existing is None:
        return dict(incoming)
    merged = dict(existing)
    merged.update(incoming)
    return merged


def _try_parse_partial_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError, ValueError:
        return None


def _iter_parts(state: _State) -> list[Part]:
    return cast("list[Part]", state.message["parts"])


def _get_tool_invocation(state: _State, tool_call_id: str) -> Part | None:
    for part in _iter_parts(state):
        if _is_tool_part(part) and part.get("toolCallId") == tool_call_id:
            return part
    return None


def _is_result_state(state_value: str) -> bool:
    return state_value in {"output-available", "output-error"}


def _provider_metadata_key(state_value: str) -> str:
    return (
        "resultProviderMetadata"
        if _is_result_state(state_value)
        else "callProviderMetadata"
    )


def _apply_optional(part: Part, key: str, value: Any) -> None:
    if value is not None:
        part[key] = value


def _build_tool_part(update: _ToolUpdate) -> Part:
    type_field = "dynamic-tool" if update.dynamic else f"tool-{update.tool_name}"
    part: Part = {
        "type": type_field,
        "toolCallId": update.tool_call_id,
        "state": update.state_value,
    }
    if update.dynamic:
        part["toolName"] = update.tool_name
    _apply_optional(part, "title", update.title)
    _apply_optional(part, "input", update.input_value)
    _apply_optional(part, "output", update.output)
    _apply_optional(part, "rawInput", update.raw_input)
    _apply_optional(part, "errorText", update.error_text)
    _apply_optional(part, "providerExecuted", update.provider_executed)
    _apply_optional(part, "preliminary", update.preliminary)
    if update.provider_metadata is not None:
        part[_provider_metadata_key(update.state_value)] = update.provider_metadata
    return part


def _patch_tool_part(part: Part, update: _ToolUpdate) -> None:
    part["state"] = update.state_value
    if update.dynamic:
        part["toolName"] = update.tool_name
    _apply_optional(part, "title", update.title)
    _apply_optional(part, "input", update.input_value)
    _apply_optional(part, "output", update.output)
    _apply_optional(part, "rawInput", update.raw_input)
    _apply_optional(part, "errorText", update.error_text)
    _apply_optional(part, "providerExecuted", update.provider_executed)
    _apply_optional(part, "preliminary", update.preliminary)
    if update.provider_metadata is not None:
        part[_provider_metadata_key(update.state_value)] = update.provider_metadata


def _find_tool_part_by_id(
    state: _State,
    tool_call_id: str,
    *,
    dynamic: bool,
) -> Part | None:
    for part in _iter_parts(state):
        if part.get("toolCallId") != tool_call_id:
            continue
        if dynamic and part.get("type") == "dynamic-tool":
            return part
        if not dynamic and _is_static_tool_part(part):
            return part
    return None


def _upsert_tool_part(state: _State, update: _ToolUpdate) -> None:
    existing = _find_tool_part_by_id(
        state,
        update.tool_call_id,
        dynamic=update.dynamic,
    )
    if existing is not None:
        _patch_tool_part(existing, update)
    else:
        state.message["parts"].append(_build_tool_part(update))


def _tool_name_from_part(invocation: Part) -> str:
    if invocation.get("type") == "dynamic-tool":
        name = invocation.get("toolName")
        return str(name) if name is not None else ""
    type_field = invocation.get("type")
    if isinstance(type_field, str) and type_field.startswith("tool-"):
        return type_field.removeprefix("tool-")
    return ""


# ---------------------------------------------------------------------------
# Per-chunk-type handlers
# ---------------------------------------------------------------------------
