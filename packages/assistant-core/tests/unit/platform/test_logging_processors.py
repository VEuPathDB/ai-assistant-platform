"""Tests for structlog processors: app context and OTEL context injection."""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

from assistant_core.platform.context import (
    operation_id_ctx,
    site_id_ctx,
    stream_id_ctx,
    user_id_ctx,
)
from assistant_core.platform.logging import add_app_context, add_otel_context


def test_add_app_context_injects_all_vars():
    uid = uuid4()
    user_id_ctx.set(uid)
    site_id_ctx.set("plasmodb")
    stream_id_ctx.set("stream-123")
    operation_id_ctx.set("op_abc")

    event_dict: dict[str, object] = {"event": "test"}
    result = add_app_context(logging.getLogger(), "", event_dict)

    assert result["user_id"] == str(uid)
    assert result["site_id"] == "plasmodb"
    assert result["stream_id"] == "stream-123"
    assert result["operation_id"] == "op_abc"


def test_add_app_context_skips_none_values():
    user_id_ctx.set(None)
    site_id_ctx.set(None)
    stream_id_ctx.set(None)
    operation_id_ctx.set(None)

    event_dict: dict[str, object] = {"event": "test"}
    result = add_app_context(logging.getLogger(), "", event_dict)

    assert "user_id" not in result
    assert "site_id" not in result
    assert "stream_id" not in result
    assert "operation_id" not in result


def test_add_otel_context_with_no_active_span():
    event_dict: dict[str, object] = {"event": "test"}
    result = add_otel_context(logging.getLogger(), "", event_dict)
    assert "trace_id" not in result
    assert "span_id" not in result


def test_add_otel_context_with_active_span():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = True
    mock_ctx = MagicMock()
    mock_ctx.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
    mock_ctx.span_id = 0x1234567890ABCDEF
    mock_span.get_span_context.return_value = mock_ctx

    with patch(
        "assistant_core.platform.logging.trace.get_current_span", return_value=mock_span
    ):
        event_dict: dict[str, object] = {"event": "test"}
        result = add_otel_context(logging.getLogger(), "", event_dict)

    assert result["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert result["span_id"] == "1234567890abcdef"
