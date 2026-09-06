"""The order the platform wraps a tool source in, and what each layer sees."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool
from pydantic_ai.toolsets.approval_required import ApprovalRequiredToolset
from pydantic_ai.toolsets.filtered import FilteredToolset
from pydantic_ai.toolsets.prefixed import PrefixedToolset
from pydantic_ai.usage import RunUsage
from pydantic_core import SchemaValidator, core_schema

from assistant_core.mcp.admission import AdmissionRecord
from assistant_core.mcp.approval import build_approval_predicate
from assistant_core.mcp.declaration import ToolSourceDeclaration
from assistant_core.mcp.untrusted import (
    PartNamespaceViolationError,
    ScanVerdict,
    UntrustedOutputToolset,
)
from assistant_core.mcp.wrapping import wrap_source

ADMITTED = AdmissionRecord(
    source_id="veupathdb-eda",
    endpoint="https://eda.example/mcp",
    part_namespace="eda",
)
DECLARATION = ToolSourceDeclaration(name="eda", source_id="veupathdb-eda")
ANNOTATIONS: dict[str, dict[str, Any] | None] = {
    "read_thing": {"readOnlyHint": True, "destructiveHint": False},
    "write_thing": {"readOnlyHint": False, "destructiveHint": True},
    "plain_thing": None,
}


def _ctx() -> RunContext[None]:
    return RunContext[None](deps=None, model=TestModel(), usage=RunUsage())


@dataclass
class _Server(AbstractToolset[None]):
    """One read-only tool, one destructive tool, one that annotates nothing."""

    meta: dict[str, Any] | None = None
    calls: list[str] = field(default_factory=list[str])

    @property
    def id(self) -> str | None:
        return "server"

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        return {
            name: ToolsetTool(
                toolset=self,
                tool_def=ToolDefinition(
                    name=name,
                    metadata={
                        "meta": self.meta,
                        "annotations": annotations,
                        "task": False,
                    },
                ),
                max_retries=0,
                args_validator=SchemaValidator(core_schema.any_schema()),
            )
            for name, annotations in ANNOTATIONS.items()
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        self.calls.append(name)
        return f"{name} ran"


def _stack(
    server: _Server,
    declaration: ToolSourceDeclaration = DECLARATION,
    **overrides: Any,
) -> AbstractToolset[Any]:
    return wrap_source(
        server,
        admitted=ADMITTED,
        declaration=declaration,
        predicate=build_approval_predicate(ADMITTED, declaration),
        **overrides,
    )


async def _call(stack: AbstractToolset[Any], name: str) -> Any:
    ctx = _ctx()
    tool = (await stack.get_tools(ctx))[name]
    return await stack.call_tool(name, {}, ctx, tool)


async def test_the_stack_is_approval_scan_filter_prefix_then_the_source() -> None:
    server = _Server()

    stack = _stack(server)

    assert isinstance(stack, ApprovalRequiredToolset)
    scan = stack.wrapped
    assert isinstance(scan, UntrustedOutputToolset)
    allow_list = scan.wrapped
    assert isinstance(allow_list, FilteredToolset)
    prefix = allow_list.wrapped
    assert isinstance(prefix, PrefixedToolset)
    assert prefix.wrapped is server


async def test_each_layer_carries_what_the_declaration_and_the_record_say() -> None:
    predicate = build_approval_predicate(ADMITTED, DECLARATION)

    stack = wrap_source(
        _Server(),
        admitted=ADMITTED,
        declaration=DECLARATION,
        predicate=predicate,
    )

    assert isinstance(stack, ApprovalRequiredToolset)
    assert stack.approval_required_func is predicate
    scan = stack.wrapped
    assert isinstance(scan, UntrustedOutputToolset)
    assert scan.part_namespace == "eda"
    prefix = scan.wrapped.wrapped
    assert isinstance(prefix, PrefixedToolset)
    assert prefix.prefix == "eda"


async def test_the_tools_reach_the_model_under_the_local_name() -> None:
    stack = _stack(_Server())

    tools = await stack.get_tools(_ctx())

    assert set(tools) == {"eda_read_thing", "eda_write_thing", "eda_plain_thing"}


async def test_the_allow_list_names_the_servers_own_tools() -> None:
    declaration = ToolSourceDeclaration(
        name="eda",
        source_id="veupathdb-eda",
        tools=["read_thing"],
    )

    stack = _stack(_Server(), declaration)

    assert set(await stack.get_tools(_ctx())) == {"eda_read_thing"}


async def test_a_declaration_without_an_allow_list_keeps_every_tool() -> None:
    stack = _stack(_Server())

    assert len(await stack.get_tools(_ctx())) == len(ANNOTATIONS)


async def test_a_read_only_tool_runs_without_asking() -> None:
    server = _Server()

    assert await _call(_stack(server), "eda_read_thing") == "read_thing ran"
    assert server.calls == ["read_thing"]


@pytest.mark.parametrize("tool", ["eda_write_thing", "eda_plain_thing"])
async def test_a_destructive_or_unannotated_tool_stops_for_approval(
    tool: str,
) -> None:
    server = _Server()
    stack = _stack(server)

    with pytest.raises(ApprovalRequired):
        await _call(stack, tool)

    assert server.calls == []


async def test_nothing_a_tool_could_return_reaches_the_approval_decision() -> None:
    scanned: list[str] = []

    async def record(text: str) -> ScanVerdict:
        scanned.append(text)
        return ScanVerdict(text=text)

    server = _Server()
    stack = _stack(server, scan=record)

    with pytest.raises(ApprovalRequired):
        await _call(stack, "eda_write_thing")

    assert scanned == []


async def test_a_namespace_the_record_does_not_admit_is_refused_through_the_stack() -> (
    None
):
    server = _Server(
        meta={
            "org.veupathdb.assistant/streamPart": {
                "kind": "data-wdk.thing",
                "version": 1,
            },
        },
    )

    with pytest.raises(PartNamespaceViolationError):
        await _stack(server).get_tools(_ctx())
