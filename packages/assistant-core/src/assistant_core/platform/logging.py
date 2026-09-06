"""Structured logging configuration."""

import logging
import sys
from typing import cast

import structlog
from opentelemetry import trace
from structlog.types import EventDict, Processor

from assistant_core.platform.config import get_runtime_settings
from assistant_core.platform.context import (
    operation_id_ctx,
    request_id_ctx,
    site_id_ctx,
    stream_id_ctx,
    user_id_ctx,
)


def add_request_id(
    logger: logging.Logger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Add request ID to log entries if available.

    :param logger: Logger instance.
    :param _method_name: Method name (structlog processor convention).
    :param event_dict: Log event dictionary to modify.
    :returns: Updated event dict.
    """
    request_id = request_id_ctx.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def add_app_context(
    logger: logging.Logger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject application context (user, site, conversation) into log events."""
    uid = user_id_ctx.get()
    if uid is not None:
        event_dict["user_id"] = str(uid)
    sid = site_id_ctx.get()
    if sid is not None:
        event_dict["site_id"] = sid
    stream = stream_id_ctx.get()
    if stream is not None:
        event_dict["stream_id"] = stream
    op = operation_id_ctx.get()
    if op is not None:
        event_dict["operation_id"] = op
    return event_dict


def add_otel_context(
    logger: logging.Logger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject OTEL trace/span IDs into log events for trace-log correlation."""
    span = trace.get_current_span()
    if not span.is_recording():
        return event_dict
    ctx = span.get_span_context()
    event_dict["trace_id"] = format(ctx.trace_id, "032x")
    event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def setup_logging() -> None:
    """Configure structured logging."""
    settings = get_runtime_settings()

    # Common processors
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        add_request_id,
        add_app_context,
        add_otel_context,
    ]

    if settings.log_format == "json":
        # JSON formatting for production
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Console formatting for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Surface uvicorn request lines (and 4xx/5xx) in `docker logs`.
    # uvicorn ships with propagate=False; flip it so events reach the root
    # handler we just installed.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.setLevel(logging.INFO)
        uv_logger.propagate = True
        # Drop uvicorn's own stderr handlers so we don't double-log.
        uv_logger.handlers.clear()


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a structlog logger.

    :param name: Logger name (typically __name__).
    :returns: Configured bound logger.
    """
    logger = structlog.get_logger(name)
    # structlog.get_logger returns a BoundLogger after configuration
    return cast("structlog.BoundLogger", logger)
