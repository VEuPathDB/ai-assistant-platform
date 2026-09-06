"""The in-process MCP server the tool-source suite runs against.

Three tools cover the approval predicate: a read-only tool that also declares a
stream part, a destructive tool, and a tool that declares no annotations. No
socket is opened and no container is started.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from assistant_core.mcp.admission import (
    AdmissionRecord,
    AdmittedSources,
    ApprovalPolicy,
    CredentialMode,
)
from assistant_core.mcp.declaration import ToolSourceDeclaration
from assistant_core.mcp.untrusted import STREAM_PART_META_KEY

SOURCE_ID = "catalog-server"
SOURCE_NAME = "catalog"
PART_NAMESPACE = "catalog"

# The credential a source's provider answers with, so a leak is greppable.
SENTINEL_TOKEN = "sentinel-user-token"
STREAM_PART_KIND = f"data-{PART_NAMESPACE}.thing"

# Nothing dials this: the suite hands the resolver an in-process server.
IN_PROCESS_ENDPOINT = "http://in-process.invalid/mcp"

THING_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["label", "count"],
}


def build_tool_server() -> FastMCP:
    """A fresh server, so one test's session never outlives another's."""
    server: FastMCP = FastMCP("catalog")

    @server.tool(
        annotations={"readOnlyHint": True},
        output_schema=THING_OUTPUT_SCHEMA,
        meta={STREAM_PART_META_KEY: {"kind": STREAM_PART_KIND, "version": 1}},
    )
    def read_thing(name: str) -> dict[str, Any]:
        """Read one thing."""
        return {"label": name, "count": 3}

    @server.tool(annotations={"destructiveHint": True})
    def write_thing(name: str) -> str:
        """Write one thing."""
        return f"wrote {name}"

    @server.tool
    def plain_thing() -> str:
        """Do a thing the server says nothing about."""
        return "plain"

    return server


def catalog_record(
    *,
    credential_mode: CredentialMode = "none",
    approval_policy: ApprovalPolicy = "annotations",
    endpoint: str = IN_PROCESS_ENDPOINT,
) -> AdmissionRecord:
    """The admission record for the in-process catalog server."""
    return AdmissionRecord(
        source_id=SOURCE_ID,
        endpoint=endpoint,
        credential_mode=credential_mode,
        part_namespace=PART_NAMESPACE,
        approval_policy=approval_policy,
    )


def catalog_admitted(**kwargs: Any) -> AdmittedSources:
    """An admitted set holding only the catalog server."""
    return AdmittedSources(records=(catalog_record(**kwargs),))


def catalog_declaration(
    *,
    name: str = SOURCE_NAME,
    source_id: str = SOURCE_ID,
    required: bool = False,
    tools: frozenset[str] | None = None,
    always_approve: frozenset[str] = frozenset(),
) -> ToolSourceDeclaration:
    """What an assistant declares when it wants the catalog server."""
    return ToolSourceDeclaration(
        name=name,
        source_id=source_id,
        required=required,
        tools=tools,
        always_approve=always_approve,
    )
