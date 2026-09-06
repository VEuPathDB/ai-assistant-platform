"""The one order the platform wraps a tool source in."""

from collections.abc import Callable
from typing import Any

from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.toolsets.filtered import FilteredToolset
from pydantic_ai.toolsets.prefixed import PrefixedToolset

from assistant_core.mcp.admission import AdmissionRecord
from assistant_core.mcp.approval import ApprovalPredicate, source_tool_name
from assistant_core.mcp.declaration import ToolSourceDeclaration
from assistant_core.mcp.untrusted import (
    OutputScan,
    UntrustedOutputToolset,
    pass_through_scan,
)


def wrap_source(
    toolset: AbstractToolset[Any],
    *,
    admitted: AdmissionRecord,
    declaration: ToolSourceDeclaration,
    predicate: ApprovalPredicate,
    scan: OutputScan = pass_through_scan,
) -> AbstractToolset[Any]:
    """Approval outside, untrusted-scan inside, filter, prefix, transport."""
    return ApprovalRequiredToolset(
        UntrustedOutputToolset(
            FilteredToolset(
                PrefixedToolset(toolset, prefix=declaration.name),
                filter_func=_declared_tools(declaration),
            ),
            part_namespace=admitted.part_namespace,
            scan=scan,
        ),
        approval_required_func=predicate,
    )


def _declared_tools(
    declaration: ToolSourceDeclaration,
) -> Callable[[RunContext[Any], ToolDefinition], bool]:
    def is_declared(ctx: RunContext[Any], tool_def: ToolDefinition) -> bool:
        del ctx
        allowed = declaration.tools
        return (
            allowed is None or source_tool_name(tool_def.name, declaration) in allowed
        )

    return is_declared


__all__ = ["wrap_source"]
