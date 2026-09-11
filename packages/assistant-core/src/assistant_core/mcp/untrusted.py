"""A source's result is untrusted text, and only a declared payload binds a part."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset
from pydantic_ai.ui.vercel_ai.response_types import DataChunk
from pydantic_core import to_json

from assistant_core.graph.stream_events import tool_summary_event
from assistant_core.platform.logging import get_logger

# The reverse-DNS namespace a tool server declares its runtime hints under.
# A deployment that runs its own runtime names its own.
DEFAULT_MCP_META_NAMESPACE = "org.veupathdb.assistant"

logger = get_logger(__name__)


class _MetaNamespace:
    """The namespace in force. The host installs it, at start."""

    def __init__(self) -> None:
        self._namespace = DEFAULT_MCP_META_NAMESPACE

    def use(self, namespace: str) -> None:
        self._namespace = namespace

    def read(self) -> str:
        return self._namespace


_namespace = _MetaNamespace()


def install_mcp_meta_namespace(namespace: str) -> None:
    """Read every tool hint under this namespace for this process."""
    _namespace.use(namespace)


def mcp_meta_namespace() -> str:
    """The namespace this deployment reads tool hints under."""
    return _namespace.read()


def stream_part_meta_key() -> str:
    """The tool-level key a server declares its typed part under."""
    return f"{mcp_meta_namespace()}/streamPart"


class StreamPartDeclaration(BaseModel):
    """The typed part a tool promises its structured payload fills."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: str = Field(min_length=1)
    version: int = Field(ge=1)


class _DeclaringToolView(BaseModel):
    """The tool metadata a part declaration arrives in.

    The key the declaration sits under is the deployment's, so the keys are
    read as data rather than typed as fields.
    """

    model_config = ConfigDict(extra="ignore")

    meta: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("meta", mode="before")
    @classmethod
    def _absent_meta_declares_nothing(
        cls,
        value: dict[str, JsonValue] | None,
    ) -> dict[str, JsonValue]:
        """A tool that carries no ``_meta`` declares no part."""
        return value or {}


class ScanVerdict(BaseModel):
    """What the guard leaves of a tool result."""

    model_config = ConfigDict(frozen=True)

    text: str


type OutputScan = Callable[[str], Awaitable[ScanVerdict]]


async def pass_through_scan(text: str) -> ScanVerdict:
    """The seam a deployment replaces. It reads the text and removes nothing."""
    return ScanVerdict(text=text)


class PartViolation(BaseModel):
    """A part a tool declared and its own payload did not satisfy."""

    model_config = ConfigDict(frozen=True)

    tool_name: str
    kind: str
    reason: str


type ViolationSink = Callable[[PartViolation], None]


def log_violation(violation: PartViolation) -> None:
    """Record a part a source declared and did not deliver."""
    logger.warning("mcp_stream_part_violation", **violation.model_dump())


class PartNamespaceViolationError(ValueError):
    """A tool claims a part kind outside the namespace its source is admitted for."""

    def __init__(self, tool_name: str, kind: str, namespace: str) -> None:
        super().__init__(
            f"{tool_name} claims {kind}, outside the data-{namespace}. namespace",
        )
        self.tool_name = tool_name
        self.kind = kind
        self.namespace = namespace


@dataclass
class UntrustedOutputToolset(WrapperToolset[AgentDepsT]):
    """Scans one source's results, and binds a declared payload to a data part."""

    part_namespace: str
    scan: OutputScan = pass_through_scan
    record_violation: ViolationSink = log_violation

    async def get_tools(
        self,
        ctx: RunContext[AgentDepsT],
    ) -> dict[str, ToolsetTool[AgentDepsT]]:
        tools = await super().get_tools(ctx)
        for name, tool in tools.items():
            declared = _declared_part(tool.tool_def.metadata)
            if declared is not None and not declared.kind.startswith(self._kind_prefix):
                raise PartNamespaceViolationError(
                    name,
                    declared.kind,
                    self.part_namespace,
                )
        return tools

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],
        tool: ToolsetTool[AgentDepsT],
    ) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)
        text = _as_text(result)
        verdict = await self.scan(text)
        if verdict.text != text:
            return verdict.text
        declared = _declared_part(tool.tool_def.metadata)
        if declared is None:
            return _answered(result, name, ctx.tool_call_id, ())
        refusal = _schema_refusal(result, tool.tool_def.return_schema)
        if refusal is not None:
            self.record_violation(
                PartViolation(tool_name=name, kind=declared.kind, reason=refusal),
            )
            return _answered(result, name, ctx.tool_call_id, ())
        part = DataChunk(type=declared.kind, data=result)
        return _answered(result, name, ctx.tool_call_id, (part,))

    @property
    def _kind_prefix(self) -> str:
        return f"data-{self.part_namespace}."


def _answered(
    result: Any,
    tool_name: str,
    tool_call_id: str | None,
    parts: tuple[DataChunk, ...],
) -> Any:
    """The result, with its declared part and the line saying the source answered.

    A call with no id is unaddressable, so it keeps whatever it already carries.
    """
    if tool_call_id is None:
        return (
            ToolReturn(return_value=result, metadata=list(parts)) if parts else result
        )
    summary = tool_summary_event(
        tool_call_id=tool_call_id,
        summary=f"{tool_name} returned",
    )
    return ToolReturn(return_value=result, metadata=[*parts, summary])


def _declared_part(metadata: dict[str, Any] | None) -> StreamPartDeclaration | None:
    meta = _DeclaringToolView.model_validate(metadata or {}).meta
    declared = meta.get(stream_part_meta_key())
    if declared is None:
        return None
    return StreamPartDeclaration.model_validate(declared)


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return to_json(result, serialize_unknown=True).decode()


def _schema_refusal(payload: Any, schema: dict[str, Any] | None) -> str | None:
    if schema is None:
        return "the tool declares a stream part and no output schema"
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except (jsonschema.ValidationError, jsonschema.SchemaError) as error:
        return str(error.message)
    return None


__all__ = [
    "DEFAULT_MCP_META_NAMESPACE",
    "OutputScan",
    "PartNamespaceViolationError",
    "PartViolation",
    "ScanVerdict",
    "StreamPartDeclaration",
    "UntrustedOutputToolset",
    "ViolationSink",
    "install_mcp_meta_namespace",
    "log_violation",
    "mcp_meta_namespace",
    "pass_through_scan",
    "stream_part_meta_key",
]
