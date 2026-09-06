from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

from assistant_core.conversation._chunk_state import (
    Chunk,
    Part,
    _apply_optional,
    _find_tool_part_by_id,
    _get_tool_invocation,
    _is_static_tool_part,
    _is_tool_part,
    _merge_metadata,
    _PartialToolCall,
    _State,
    _tool_name_from_part,
    _ToolUpdate,
    _try_parse_partial_json,
    _upsert_tool_part,
)
from assistant_core.graph.stream_events import ToolSummaryPayload

TOOL_SUMMARY_KIND = "data-tool-summary"


def _h_text_start(state: _State, chunk: Chunk) -> None:
    chunk_id = str(chunk["id"])
    text_part: Part = {
        "type": "text",
        "text": "",
        "providerMetadata": chunk.get("providerMetadata"),
        "state": "streaming",
    }
    state.active_text_parts[chunk_id] = text_part
    state.message["parts"].append(text_part)


def _h_text_delta(state: _State, chunk: Chunk) -> None:
    text_part = state.active_text_parts.get(str(chunk["id"]))
    if text_part is None:
        return
    text_part["text"] += chunk.get("delta", "")
    if chunk.get("providerMetadata") is not None:
        text_part["providerMetadata"] = chunk["providerMetadata"]


def _h_text_end(state: _State, chunk: Chunk) -> None:
    chunk_id = str(chunk["id"])
    text_part = state.active_text_parts.get(chunk_id)
    if text_part is None:
        return
    text_part["state"] = "done"
    if chunk.get("providerMetadata") is not None:
        text_part["providerMetadata"] = chunk["providerMetadata"]
    del state.active_text_parts[chunk_id]


def _h_reasoning_start(state: _State, chunk: Chunk) -> None:
    chunk_id = str(chunk["id"])
    part: Part = {
        "type": "reasoning",
        "text": "",
        "providerMetadata": chunk.get("providerMetadata"),
        "state": "streaming",
    }
    state.active_reasoning_parts[chunk_id] = part
    state.message["parts"].append(part)


def _h_reasoning_delta(state: _State, chunk: Chunk) -> None:
    part = state.active_reasoning_parts.get(str(chunk["id"]))
    if part is None:
        return
    part["text"] += chunk.get("delta", "")
    if chunk.get("providerMetadata") is not None:
        part["providerMetadata"] = chunk["providerMetadata"]


def _h_reasoning_end(state: _State, chunk: Chunk) -> None:
    chunk_id = str(chunk["id"])
    part = state.active_reasoning_parts.get(chunk_id)
    if part is None:
        return
    part["state"] = "done"
    if chunk.get("providerMetadata") is not None:
        part["providerMetadata"] = chunk["providerMetadata"]
    del state.active_reasoning_parts[chunk_id]


def _h_file(state: _State, chunk: Chunk) -> None:
    part: Part = {
        "type": "file",
        "mediaType": chunk.get("mediaType"),
        "url": chunk.get("url"),
    }
    _apply_optional(part, "providerMetadata", chunk.get("providerMetadata"))
    state.message["parts"].append(part)


def _h_source_url(state: _State, chunk: Chunk) -> None:
    state.message["parts"].append(
        {
            "type": "source-url",
            "sourceId": chunk.get("sourceId"),
            "url": chunk.get("url"),
            "title": chunk.get("title"),
            "providerMetadata": chunk.get("providerMetadata"),
        },
    )


def _h_source_document(state: _State, chunk: Chunk) -> None:
    state.message["parts"].append(
        {
            "type": "source-document",
            "sourceId": chunk.get("sourceId"),
            "mediaType": chunk.get("mediaType"),
            "title": chunk.get("title"),
            "filename": chunk.get("filename"),
            "providerMetadata": chunk.get("providerMetadata"),
        },
    )


def _h_tool_input_start(state: _State, chunk: Chunk) -> None:
    tool_call_id = str(chunk["toolCallId"])
    tool_name = str(chunk["toolName"])
    dynamic = bool(chunk.get("dynamic", False))
    existing_static = sum(1 for p in state.message["parts"] if _is_static_tool_part(p))
    state.partial_tool_calls[tool_call_id] = _PartialToolCall(
        text="",
        tool_name=tool_name,
        index=existing_static,
        dynamic=dynamic,
        title=chunk.get("title"),
    )
    _upsert_tool_part(
        state,
        _ToolUpdate(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            state_value="input-streaming",
            dynamic=dynamic,
            title=chunk.get("title"),
            provider_executed=chunk.get("providerExecuted"),
            provider_metadata=chunk.get("providerMetadata"),
        ),
    )


def _h_tool_input_delta(state: _State, chunk: Chunk) -> None:
    tool_call_id = str(chunk["toolCallId"])
    partial = state.partial_tool_calls.get(tool_call_id)
    if partial is None:
        return
    partial.text += chunk.get("inputTextDelta", "")
    _upsert_tool_part(
        state,
        _ToolUpdate(
            tool_call_id=tool_call_id,
            tool_name=partial.tool_name,
            state_value="input-streaming",
            dynamic=partial.dynamic,
            input_value=_try_parse_partial_json(partial.text),
            title=partial.title,
        ),
    )


def _h_tool_input_available(state: _State, chunk: Chunk) -> None:
    _upsert_tool_part(
        state,
        _ToolUpdate(
            tool_call_id=str(chunk["toolCallId"]),
            tool_name=str(chunk["toolName"]),
            state_value="input-available",
            dynamic=bool(chunk.get("dynamic", False)),
            input_value=chunk.get("input"),
            provider_executed=chunk.get("providerExecuted"),
            provider_metadata=chunk.get("providerMetadata"),
            title=chunk.get("title"),
        ),
    )


def _h_tool_input_error(state: _State, chunk: Chunk) -> None:
    tool_call_id = str(chunk["toolCallId"])
    tool_name = str(chunk["toolName"])
    existing = next(
        (
            p
            for p in state.message["parts"]
            if _is_tool_part(p) and p.get("toolCallId") == tool_call_id
        ),
        None,
    )
    is_dynamic = (
        existing.get("type") == "dynamic-tool"
        if existing is not None
        else bool(chunk.get("dynamic", False))
    )
    update = _ToolUpdate(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        state_value="output-error",
        dynamic=is_dynamic,
        error_text=chunk.get("errorText"),
        provider_executed=chunk.get("providerExecuted"),
        provider_metadata=chunk.get("providerMetadata"),
    )
    if is_dynamic:
        update.input_value = chunk.get("input")
    else:
        update.raw_input = chunk.get("input")
    _upsert_tool_part(state, update)


def _h_tool_approval_request(state: _State, chunk: Chunk) -> None:
    invocation = _get_tool_invocation(state, str(chunk["toolCallId"]))
    if invocation is None:
        return
    invocation["state"] = "approval-requested"
    invocation["approval"] = {"id": chunk.get("approvalId")}


def _h_tool_output_denied(state: _State, chunk: Chunk) -> None:
    invocation = _get_tool_invocation(state, str(chunk["toolCallId"]))
    if invocation is None:
        return
    invocation["state"] = "output-denied"


def _h_tool_output_available(state: _State, chunk: Chunk) -> None:
    invocation = _get_tool_invocation(state, str(chunk["toolCallId"]))
    if invocation is None:
        return
    is_dynamic = invocation.get("type") == "dynamic-tool"
    _upsert_tool_part(
        state,
        _ToolUpdate(
            tool_call_id=str(chunk["toolCallId"]),
            tool_name=_tool_name_from_part(invocation),
            state_value="output-available",
            dynamic=is_dynamic,
            input_value=invocation.get("input"),
            output=chunk.get("output"),
            preliminary=chunk.get("preliminary"),
            provider_executed=chunk.get("providerExecuted"),
            provider_metadata=chunk.get("providerMetadata"),
            title=invocation.get("title"),
        ),
    )


def _h_tool_output_error(state: _State, chunk: Chunk) -> None:
    invocation = _get_tool_invocation(state, str(chunk["toolCallId"]))
    if invocation is None:
        return
    is_dynamic = invocation.get("type") == "dynamic-tool"
    _upsert_tool_part(
        state,
        _ToolUpdate(
            tool_call_id=str(chunk["toolCallId"]),
            tool_name=_tool_name_from_part(invocation),
            state_value="output-error",
            dynamic=is_dynamic,
            input_value=invocation.get("input"),
            raw_input=invocation.get("rawInput"),
            error_text=chunk.get("errorText"),
            provider_executed=chunk.get("providerExecuted"),
            provider_metadata=chunk.get("providerMetadata"),
            title=invocation.get("title"),
        ),
    )


def _h_start_step(state: _State, _chunk: Chunk) -> None:
    state.message["parts"].append({"type": "step-start"})


def _h_finish_step(state: _State, _chunk: Chunk) -> None:
    state.active_text_parts.clear()
    state.active_reasoning_parts.clear()


def _h_start(state: _State, chunk: Chunk) -> None:
    if chunk.get("messageId") is not None:
        state.message["id"] = chunk["messageId"]
    meta = chunk.get("messageMetadata")
    if meta is not None:
        state.message["metadata"] = _merge_metadata(
            state.message.get("metadata"),
            meta,
        )


def _h_finish(state: _State, chunk: Chunk) -> None:
    if chunk.get("finishReason") is not None:
        state.finish_reason = chunk["finishReason"]
    meta = chunk.get("messageMetadata")
    if meta is not None:
        state.message["metadata"] = _merge_metadata(
            state.message.get("metadata"),
            meta,
        )


def _h_message_metadata(state: _State, chunk: Chunk) -> None:
    meta = chunk.get("messageMetadata")
    if meta is not None:
        state.message["metadata"] = _merge_metadata(
            state.message.get("metadata"),
            meta,
        )


def _read_tool_summary(chunk: Chunk) -> ToolSummaryPayload | None:
    """The summary a chunk carries, or nothing when the wire malformed it."""
    try:
        return ToolSummaryPayload.model_validate(chunk.get("data"))
    except ValidationError:
        return None


def _h_tool_summary(state: _State, chunk: Chunk) -> None:
    payload = _read_tool_summary(chunk)
    if payload is None:
        return
    part = _find_tool_part_by_id(
        state,
        payload.tool_call_id,
        dynamic=False,
    ) or _find_tool_part_by_id(state, payload.tool_call_id, dynamic=True)
    if part is None:
        return
    part["summary"] = payload.summary
    part["summaryStatus"] = payload.status


def _h_data(state: _State, chunk: Chunk) -> None:
    if chunk.get("transient"):
        return
    if chunk.get("type") == TOOL_SUMMARY_KIND:
        _h_tool_summary(state, chunk)
        return
    chunk_id = chunk.get("id")
    chunk_type = chunk.get("type")
    if chunk_id is not None:
        for part in state.message["parts"]:
            if part.get("type") == chunk_type and part.get("id") == chunk_id:
                part["data"] = chunk.get("data")
                return
    state.message["parts"].append(dict(chunk))


_HANDLERS: dict[str, Callable[[_State, Chunk], None]] = {
    "text-start": _h_text_start,
    "text-delta": _h_text_delta,
    "text-end": _h_text_end,
    "reasoning-start": _h_reasoning_start,
    "reasoning-delta": _h_reasoning_delta,
    "reasoning-end": _h_reasoning_end,
    "file": _h_file,
    "source-url": _h_source_url,
    "source-document": _h_source_document,
    "tool-input-start": _h_tool_input_start,
    "tool-input-delta": _h_tool_input_delta,
    "tool-input-available": _h_tool_input_available,
    "tool-input-error": _h_tool_input_error,
    "tool-approval-request": _h_tool_approval_request,
    "tool-output-denied": _h_tool_output_denied,
    "tool-output-available": _h_tool_output_available,
    "tool-output-error": _h_tool_output_error,
    "start-step": _h_start_step,
    "finish-step": _h_finish_step,
    "start": _h_start,
    "finish": _h_finish,
    "message-metadata": _h_message_metadata,
}


def _apply_chunk(state: _State, chunk: Chunk) -> None:
    chunk_type = chunk.get("type")
    if not isinstance(chunk_type, str):
        return
    handler = _HANDLERS.get(chunk_type)
    if handler is not None:
        handler(state, chunk)
        return
    if chunk_type.startswith("data-"):
        _h_data(state, chunk)
