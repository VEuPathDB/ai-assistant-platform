"""Keep a durable job's carried state out of the queue's own log lines.

Procrastinate logs every job start with a repr of the kwargs the database
holds, and those kwargs carry whatever the host's job context captured. The
runtime owns that field, so the runtime scrubs its value.
"""

from __future__ import annotations

import logging
import re

from procrastinate.worker import WORKER_NAME

REDACTION_MARKER = "***REDACTED***"

_ROOT_LOGGER = "procrastinate"
_WORKER_LOGGER = "procrastinate.worker"

_JOB_CONTEXT_KEY = "job_context"

# The key, optionally quoted, bound to a value with either punctuation.
_OPENER = re.compile(rf"(['\"]?){_JOB_CONTEXT_KEY}\1\s*[:=]\s*(?=\{{)")


def _value_end(text: str, start: int) -> int:
    """The index after the brace-delimited value that starts at ``start``.

    A brace inside a quoted string does not change the depth. The result is
    ``-1`` when the value is cut short.
    """
    depth = 0
    quote = ""
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return -1


def redact_job_context(message: str) -> str:
    """Replace every carried-state value in a log message with the marker."""
    kept: list[str] = []
    rest = message
    while True:
        found = _OPENER.search(rest)
        if found is None:
            kept.append(rest)
            return "".join(kept)
        kept.append(rest[: found.end()])
        end = _value_end(rest, found.end())
        if end < 0:
            kept.append(rest[found.end() :])
            return "".join(kept)
        kept.append(REDACTION_MARKER)
        rest = rest[end:]


class RedactJobContextFilter(logging.Filter):
    """Scrub a durable job's carried state from an emitted log message."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_job_context(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def _procrastinate_logger_names(worker_name: str | None) -> set[str]:
    """Every logger name a durable job line can be emitted on.

    A worker logs on a child of ``procrastinate.worker`` named after itself,
    which is built after the jobs are registered, so the name is asked for
    here and the logger exists before the worker does.
    """
    names = {_ROOT_LOGGER, _WORKER_LOGGER, f"{_WORKER_LOGGER}.{WORKER_NAME}"}
    if worker_name:
        names.add(f"{_WORKER_LOGGER}.{worker_name}")
    for name in logging.Logger.manager.loggerDict:
        if name == _ROOT_LOGGER or name.startswith(f"{_ROOT_LOGGER}."):
            names.add(name)
    return names


def install_job_payload_redaction(*, worker_name: str | None = None) -> None:
    """Attach the scrub to every procrastinate logger and root handler.

    A filter does not propagate from a parent logger to its children, so the
    worker's own logger is named here, and the root handlers catch a child
    under another name. Calling this twice adds nothing.
    """
    scrub = RedactJobContextFilter()
    for name in _procrastinate_logger_names(worker_name):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactJobContextFilter) for f in logger.filters):
            logger.addFilter(scrub)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactJobContextFilter) for f in handler.filters):
            handler.addFilter(scrub)


__all__ = [
    "REDACTION_MARKER",
    "RedactJobContextFilter",
    "install_job_payload_redaction",
    "redact_job_context",
]
