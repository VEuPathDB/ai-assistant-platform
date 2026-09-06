"""What the runner told the suite: where the server is, and what it may call."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, TypeAdapter

from mcp_conformance._wire import WireModel

ENDPOINT_OPTION = "--mcp-endpoint"
BEARER_OPTION = "--mcp-bearer"
SECOND_BEARER_OPTION = "--mcp-bearer-second"
REPORT_OPTION = "--mcp-report"
SAMPLE_ARGS_OPTION = "--mcp-sample-args"
SLOW_TOOL_OPTION = "--mcp-slow-tool"
ISOLATION_TOOL_OPTION = "--mcp-isolation-tool"
MAX_CALL_SECONDS_OPTION = "--mcp-max-call-seconds"

ENDPOINT_ENV = "MCP_CONFORMANCE_ENDPOINT"
BEARER_ENV = "MCP_CONFORMANCE_BEARER"
SECOND_BEARER_ENV = "MCP_CONFORMANCE_BEARER_SECOND"

# The budget a tool that declares none is held to.
DEFAULT_MAX_CALL_SECONDS = 60.0

SampleArguments = dict[str, dict[str, Any]]
_SAMPLES = TypeAdapter(SampleArguments)


class ConformanceTarget(WireModel):
    """The server under test, the credentials, and the calls the runner allows."""

    endpoint: str
    bearer: str | None = None
    second_bearer: str | None = None
    sample_arguments: SampleArguments = Field(default_factory=dict)
    slow_tool: str | None = None
    isolation_tool: str | None = None
    max_call_seconds: float = DEFAULT_MAX_CALL_SECONDS

    @property
    def credentials(self) -> tuple[str, ...]:
        """Every secret that must not reach the report."""
        return tuple(value for value in (self.bearer, self.second_bearer) if value)


def from_environment(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def sample_arguments(value: str) -> SampleArguments:
    """A JSON object of tool arguments, given inline or as a file."""
    path = Path(value)
    text = path.read_text() if path.is_file() else value
    return _SAMPLES.validate_json(text)
