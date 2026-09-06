"""Family 6: two fresh connections read the same tools, or every client is stale.

A client caches the tool list until the server says it changed. A list that
drifts between connections leaves that cache wrong with nothing to invalidate it.
"""

from __future__ import annotations

from mcp_conformance._evidence import StabilityEvidence, ToolRecord


def _definitions(tools: list[ToolRecord]) -> dict[str, str]:
    return {tool.name: tool.model_dump_json(by_alias=True) for tool in tools}


def test_the_tool_names_are_the_same_across_two_connections(
    mcp_stability_evidence: StabilityEvidence,
) -> None:
    first = {tool.name for tool in mcp_stability_evidence.first}
    second = {tool.name for tool in mcp_stability_evidence.second}

    assert sorted(first ^ second) == []


def test_every_tool_definition_is_the_same_across_two_connections(
    mcp_stability_evidence: StabilityEvidence,
) -> None:
    first = _definitions(list(mcp_stability_evidence.first))
    second = _definitions(list(mcp_stability_evidence.second))
    drifted = sorted(
        name for name in first.keys() & second.keys() if first[name] != second[name]
    )

    assert drifted == []
