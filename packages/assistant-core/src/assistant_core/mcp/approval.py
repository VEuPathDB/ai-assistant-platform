"""Whether a tool a source serves over MCP may run before the user is asked."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai.tools import RunContext, ToolDefinition

from assistant_core.mcp.admission import AdmissionRecord
from assistant_core.mcp.declaration import ToolSourceDeclaration


class ToolAnnotationsView(BaseModel):
    """The annotation fields the predicate reads, tolerant of absence."""

    model_config = ConfigDict(extra="ignore")

    readOnlyHint: bool | None = None
    destructiveHint: bool | None = None
    openWorldHint: bool | None = None
    idempotentHint: bool | None = None


class _AnnotatedToolView(BaseModel):
    """The tool metadata a source's annotations arrive in."""

    model_config = ConfigDict(extra="ignore")

    annotations: ToolAnnotationsView | None = None


type ApprovalPredicate = Callable[
    [RunContext[Any], ToolDefinition, dict[str, Any]],
    bool,
]


def source_tool_name(name: str, declaration: ToolSourceDeclaration) -> str:
    """The name the server knows, from the name the prefix wrapper serves."""
    return name.removeprefix(f"{declaration.name}_")


def build_approval_predicate(
    admitted: AdmissionRecord | None,
    declaration: ToolSourceDeclaration,
) -> ApprovalPredicate:
    """Ask by default. An admitted read-only tool is the one silent path."""

    def approval_required(
        ctx: RunContext[Any],
        tool_def: ToolDefinition,
        tool_args: dict[str, Any],
    ) -> bool:
        del ctx, tool_args
        if source_tool_name(tool_def.name, declaration) in declaration.always_approve:
            return True
        if admitted is None or admitted.approval_policy == "always":
            return True
        annotations = _AnnotatedToolView.model_validate(
            tool_def.metadata or {},
        ).annotations
        if annotations is None:
            return True
        return not (
            annotations.readOnlyHint is True and annotations.destructiveHint is not True
        )

    return approval_required


__all__ = [
    "ApprovalPredicate",
    "ToolAnnotationsView",
    "build_approval_predicate",
    "source_tool_name",
]
