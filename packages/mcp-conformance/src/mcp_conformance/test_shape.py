"""Family 1: what the server says it is, and what its tools declare.

The report names the negotiated revision; this family does not fail on it. What
it fails on is a tool a client cannot route to, cannot describe, cannot validate
arguments for, or cannot render the payload of.
"""

from __future__ import annotations

import re

from mcp_conformance._evidence import ShapeEvidence

# SEP-986, the tool-name rule of the 2025-11-25 revision. A name outside it stops
# being one name once a client prefixes it with the source it came from.
TOOL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def test_the_handshake_names_the_server_and_a_protocol_revision(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    server = mcp_shape_evidence.server
    unnamed = [
        field
        for field, value in (
            ("serverInfo.name", server.name),
            ("serverInfo.version", server.version),
            ("protocolVersion", server.protocol_version),
        )
        if not value
    ]

    assert unnamed == []


def test_the_server_declares_the_tools_capability(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    assert mcp_shape_evidence.server.capabilities.tools is not None


def test_the_server_offers_tools(mcp_shape_evidence: ShapeEvidence) -> None:
    assert [tool.name for tool in mcp_shape_evidence.tools] != []


def test_tool_names_are_unique(mcp_shape_evidence: ShapeEvidence) -> None:
    names = [tool.name for tool in mcp_shape_evidence.tools]
    repeated = sorted({name for name in names if names.count(name) > 1})

    assert repeated == []


def test_tool_names_are_prefix_safe(mcp_shape_evidence: ShapeEvidence) -> None:
    unroutable = [
        tool.name for tool in mcp_shape_evidence.tools if not TOOL_NAME.match(tool.name)
    ]

    assert unroutable == []


def test_every_tool_describes_itself(mcp_shape_evidence: ShapeEvidence) -> None:
    undescribed = [
        tool.name
        for tool in mcp_shape_evidence.tools
        if not (tool.description or "").strip()
    ]

    assert undescribed == []


def test_every_input_schema_is_an_object_schema(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    unvalidatable = [
        f"{tool.name}: inputSchema type is {tool.schema_view.type or 'absent'!r}"
        for tool in mcp_shape_evidence.tools
        if tool.schema_view.type != "object"
    ]

    assert unvalidatable == []


def test_a_stream_part_tool_declares_an_output_schema(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    unrenderable = [
        tool.name
        for tool in mcp_shape_evidence.tools
        if tool.stream_part is not None and tool.output_schema is None
    ]

    assert unrenderable == []


def test_a_stream_part_declaration_names_a_kind_and_a_version(
    mcp_shape_evidence: ShapeEvidence,
) -> None:
    unnamed = [
        tool.name
        for tool in mcp_shape_evidence.tools
        if tool.stream_part is not None
        and not (tool.stream_part.kind and tool.stream_part.version)
    ]

    assert unnamed == []
