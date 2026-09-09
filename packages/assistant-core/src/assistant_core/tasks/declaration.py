"""One durable tool, declared once.

The decorator that defers the call, the job the worker consumes and the body
that runs on the worker all read one declaration, so the three names cannot
drift apart.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from assistant_core.graph.durable import (
    DURABLE_TOOLS,
    ChunkBuilder,
    DurableToolSpec,
    register_durable_tool,
)
from assistant_core.tasks.names import durable_job_name

type DurableToolImpl = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, kw_only=True)
class DurableTool:
    """A durable tool's name, its budget and the chunks its result carries."""

    tool_name: str
    estimated_duration_seconds: int
    chunks_from_result: ChunkBuilder | None = None

    @property
    def job_name(self) -> str:
        """The procrastinate job this tool defers."""
        return durable_job_name(self.tool_name)


class UndeclaredDurableToolError(LookupError):
    """A registration names a tool ``declare_durable_tool`` did not return."""

    def __init__(self, tool_name: str, declared: tuple[str, ...]) -> None:
        super().__init__(
            f"durable tool {tool_name!r} is not declared here: pass the value "
            "declare_durable_tool() returned, so the decorator, the job and "
            f"the worker share one name; declared: {list(declared)}",
        )
        self.tool_name = tool_name
        self.declared = declared


class DuplicateDurableToolError(ValueError):
    """Two declarations claim one tool name."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"durable tool already declared: {tool_name}")
        self.tool_name = tool_name


_DECLARED: dict[str, DurableTool] = {}
_IMPLS: dict[str, DurableToolImpl] = {}


def declare_durable_tool(
    *,
    tool_name: str,
    estimated_duration_seconds: int,
    chunks_from_result: ChunkBuilder | None = None,
) -> DurableTool:
    """Declare one durable tool and return the value everything else reads.

    ``chunks_from_result`` builds the chat-visible chunks the tool's result
    carries. It runs on the turn that delivers the worker's answer.
    """
    if tool_name in _DECLARED:
        raise DuplicateDurableToolError(tool_name)
    tool = DurableTool(
        tool_name=tool_name,
        estimated_duration_seconds=estimated_duration_seconds,
        chunks_from_result=chunks_from_result,
    )
    _DECLARED[tool_name] = tool
    register_durable_tool(
        DurableToolSpec(
            tool_name=tool.tool_name,
            estimated_duration_seconds=tool.estimated_duration_seconds,
            chunks_from_result=tool.chunks_from_result,
        ),
    )
    return tool


def require_declared(tool: DurableTool) -> DurableTool:
    """The declaration this value names. Raises when it names none."""
    found = _DECLARED.get(tool.tool_name)
    if found != tool:
        raise UndeclaredDurableToolError(tool.tool_name, tuple(_DECLARED))
    return found


def register_durable_impl(tool: DurableTool, impl: DurableToolImpl) -> None:
    """Bind the worker-side body of a declared durable tool."""
    require_declared(tool)
    _IMPLS[tool.tool_name] = impl


def durable_impl(tool_name: str) -> DurableToolImpl | None:
    """The worker-side body registered for a tool name in this process."""
    return _IMPLS.get(tool_name)


def declared_durable_tools() -> tuple[DurableTool, ...]:
    """Every durable tool declared in this process."""
    return tuple(_DECLARED.values())


@contextmanager
def empty_durable_tools() -> Iterator[None]:
    """Declare into an empty registry, and put back what was declared."""
    declared = dict(_DECLARED)
    impls = dict(_IMPLS)
    specs = dict(DURABLE_TOOLS)
    _restore({}, {}, {})
    try:
        yield
    finally:
        _restore(declared, impls, specs)


def _restore(
    declared: dict[str, DurableTool],
    impls: dict[str, DurableToolImpl],
    specs: dict[str, DurableToolSpec],
) -> None:
    _DECLARED.clear()
    _DECLARED.update(declared)
    _IMPLS.clear()
    _IMPLS.update(impls)
    DURABLE_TOOLS.clear()
    DURABLE_TOOLS.update(specs)


__all__ = [
    "DuplicateDurableToolError",
    "DurableTool",
    "DurableToolImpl",
    "UndeclaredDurableToolError",
    "declare_durable_tool",
    "declared_durable_tools",
    "durable_impl",
    "empty_durable_tools",
    "register_durable_impl",
    "require_declared",
]
