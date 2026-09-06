"""A source's result is untrusted text, and only a declared payload binds a part."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset
from pydantic_ai.ui.vercel_ai.response_types import DataChunk
from pydantic_core import to_json

from assistant_core.graph.stream_events import tool_summary_event
from assistant_core.platform.logging import get_logger

STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"

logger = get_logger(__name__)


class StreamPartDeclaration(BaseModel):
    """The typed part a tool promises its structured payload fills."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: str = Field(min_length=1)
    version: int = Field(ge=1)


class _SourceToolMeta(BaseModel):
    """The tool-level ``_meta`` keys the runtime reads."""

    model_config = ConfigDict(extra="ignore")

    stream_part: StreamPartDeclaration | None = Field(
        default=None,
        alias=STREAM_PART_META_KEY,
    )


class _DeclaringToolView(BaseModel):
    """The tool metadata a part declaration arrives in."""

    model_config = ConfigDict(extra="ignore")

    meta: _SourceToolMeta | None = None


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
    return meta.stream_part if meta is not None else None


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
    "STREAM_PART_META_KEY",
    "OutputScan",
    "PartNamespaceViolationError",
    "PartViolation",
    "ScanVerdict",
    "StreamPartDeclaration",
    "UntrustedOutputToolset",
    "ViolationSink",
    "log_violation",
    "pass_through_scan",
]
