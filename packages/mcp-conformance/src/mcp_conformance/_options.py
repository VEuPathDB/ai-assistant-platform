"""What the runner told the suite: where the server is, and what it may call."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import (
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from mcp_conformance._wire import WireModel

ENDPOINT_OPTION = "--mcp-endpoint"
BEARER_OPTION = "--mcp-bearer"
SECOND_BEARER_OPTION = "--mcp-bearer-second"
REPORT_OPTION = "--mcp-report"
SAMPLE_ARGS_OPTION = "--mcp-sample-args"
SLOW_TOOL_OPTION = "--mcp-slow-tool"
ISOLATION_TOOL_OPTION = "--mcp-isolation-tool"
MAX_CALL_SECONDS_OPTION = "--mcp-max-call-seconds"
BEARER_MINIMUM_OPTION = "--mcp-bearer-minimum"

ENDPOINT_ENV = "MCP_CONFORMANCE_ENDPOINT"
BEARER_ENV = "MCP_CONFORMANCE_BEARER"
SECOND_BEARER_ENV = "MCP_CONFORMANCE_BEARER_SECOND"
BEARER_MINIMUM_ENV = "MCP_CONFORMANCE_BEARER_MINIMUM"

# The budget a tool that declares none is held to.
DEFAULT_MAX_CALL_SECONDS = 60.0

# The shortest secret a deployment is assumed to admit an application on. A
# target whose own registry issues shorter or longer secrets states its
# minimum, and the suite refuses a bearer under it before it opens a session.
DEFAULT_BEARER_MINIMUM = 32

SampleArguments = dict[str, dict[str, Any]]
_SAMPLES = TypeAdapter(SampleArguments)


class ConformanceTarget(WireModel):
    """The server under test, the credentials, and the calls the runner allows."""

    # Pydantic renders a refused value in its error, and a refused bearer is
    # still a credential.
    model_config = ConfigDict(hide_input_in_errors=True)

    endpoint: str
    # A masked type, because pytest renders a failing frame's locals and a
    # shortened value is a value the report cannot match on.
    bearer: SecretStr | None = None
    second_bearer: SecretStr | None = None
    sample_arguments: SampleArguments = Field(default_factory=dict)
    slow_tool: str | None = None
    isolation_tool: str | None = None
    max_call_seconds: float = DEFAULT_MAX_CALL_SECONDS
    bearer_minimum: int = Field(default=DEFAULT_BEARER_MINIMUM, ge=1)

    @field_validator("bearer", "second_bearer", mode="before")
    @classmethod
    def _absent_when_empty(cls, value: str | None) -> str | None:
        """An empty option is how the runner spells no bearer at all."""
        return value or None

    @model_validator(mode="after")
    def _long_enough_to_admit(self) -> ConformanceTarget:
        for value in (self.bearer, self.second_bearer):
            if value is None:
                continue
            if len(value.get_secret_value()) < self.bearer_minimum:
                msg = (
                    f"A bearer is at least {self.bearer_minimum} characters, "
                    "the shortest secret this deployment admits."
                )
                raise ValueError(msg)
        return self

    @property
    def credentials(self) -> tuple[SecretStr, ...]:
        """Every secret that must not reach the report."""
        return tuple(
            value for value in (self.bearer, self.second_bearer) if value is not None
        )


def from_environment(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def sample_arguments(value: str) -> SampleArguments:
    """A JSON object of tool arguments, given inline or as a file."""
    path = Path(value)
    text = path.read_text() if path.is_file() else value
    return _SAMPLES.validate_json(text)
