"""The tool protocol, proven end to end against an in-process MCP server.

Each test here is one of the exit criteria the program set for its first
phase: the tool appears in a turn, approval follows the annotations, a
declared payload becomes a namespaced part, the guard reads the result before
the model does, the session closes with the turn, and the credential stops at
the transport.
"""

from __future__ import annotations

import json

from tests.mcp_runtime import McpRuntime, RuntimeFactory, ScanLog
from tests.mcp_server import SENTINEL_TOKEN, STREAM_PART_KIND, catalog_record
from tests.synthetic import (
    SOURCE_PLAIN_CALL_ID,
    SOURCE_PLAIN_PROMPT,
    SOURCE_READ_CALL_ID,
    SOURCE_READ_PROMPT,
    SOURCE_READ_TOOL,
    SOURCE_THING_NAME,
    SOURCE_WRITE_CALL_ID,
    SOURCE_WRITE_PROMPT,
)

from assistant_core.conversation.event_stream import fetch_chunks_after
from assistant_core.mcp.resolution import build_mcp_toolset

READ_PAYLOAD = {"label": SOURCE_THING_NAME, "count": 3}
SCANNED_TEXT = "[the guard removed this]"


def _of_type(
    outcome_chunks: list[dict[str, object]], kind: str
) -> list[dict[str, object]]:
    return [chunk for chunk in outcome_chunks if chunk["type"] == kind]


async def test_mcp_tool_appears_in_a_real_turn(runtime: McpRuntime) -> None:
    outcome = await runtime.run(SOURCE_READ_PROMPT)

    inputs = _of_type(outcome.chunks, "tool-input-available")
    outputs = _of_type(outcome.chunks, "tool-output-available")

    assert [chunk["toolName"] for chunk in inputs] == [SOURCE_READ_TOOL]
    assert [chunk["toolCallId"] for chunk in outputs] == [SOURCE_READ_CALL_ID]
    assert outputs[0]["output"] == READ_PAYLOAD
    assert _of_type(outcome.chunks, "error") == []


async def test_destructive_tool_asks_and_readonly_does_not(
    install_mcp: RuntimeFactory,
) -> None:
    destructive = await install_mcp()
    unannotated = await install_mcp()
    read_only = await install_mcp()

    destructive_turn = await destructive.run(SOURCE_WRITE_PROMPT)
    unannotated_turn = await unannotated.run(SOURCE_PLAIN_PROMPT)
    read_only_turn = await read_only.run(SOURCE_READ_PROMPT)

    def _asked(chunks: list[dict[str, object]]) -> list[object]:
        return [c["toolCallId"] for c in _of_type(chunks, "tool-approval-request")]

    assert _asked(destructive_turn.chunks) == [SOURCE_WRITE_CALL_ID]
    assert _asked(unannotated_turn.chunks) == [SOURCE_PLAIN_CALL_ID]
    assert _asked(read_only_turn.chunks) == []
    assert _of_type(read_only_turn.chunks, "tool-output-available") != []


async def test_the_approved_destructive_call_runs_on_the_next_turn(
    runtime: McpRuntime,
) -> None:
    await runtime.run(SOURCE_WRITE_PROMPT)

    resumed = await runtime.answer_approval(SOURCE_WRITE_CALL_ID, approved=True)

    outputs = _of_type(resumed.chunks, "tool-output-available")
    assert [chunk["output"] for chunk in outputs] == [f"wrote {SOURCE_THING_NAME}"]


async def test_declared_payload_becomes_namespaced_part(runtime: McpRuntime) -> None:
    outcome = await runtime.run(SOURCE_READ_PROMPT)

    parts = _of_type(outcome.chunks, STREAM_PART_KIND)

    assert [part["data"] for part in parts] == [READ_PAYLOAD]


async def test_an_undeclared_tool_binds_no_part(runtime: McpRuntime) -> None:
    outcome = await runtime.run(SOURCE_PLAIN_PROMPT)
    resumed = await runtime.answer_approval(SOURCE_PLAIN_CALL_ID, approved=True)

    written = outcome.chunks + resumed.chunks
    assert [c for c in written if str(c["type"]).startswith("data-catalog.")] == []


async def test_result_scanned_before_reentry(install_mcp: RuntimeFactory) -> None:
    guard = ScanLog(replacement=SCANNED_TEXT)
    runtime = await install_mcp(scan=guard)

    outcome = await runtime.run(SOURCE_READ_PROMPT)

    deltas = [c["delta"] for c in _of_type(outcome.chunks, "text-delta")]
    assert guard.seen == [json.dumps(READ_PAYLOAD, separators=(",", ":"))]
    assert deltas == [f"Result: {SCANNED_TEXT}."]


async def test_toolset_closed_per_turn(runtime: McpRuntime) -> None:
    """The turn owns the session: open at both its edges, closed after it.

    An agent run opens the toolset for its own duration, so the boundaries the
    turn is measured at sit outside every run.
    """
    await runtime.run(SOURCE_READ_PROMPT)

    assert runtime.open_before_the_agent_ran == [True]
    assert runtime.open_after_the_agent_ran == [True]
    assert [transport.is_running for transport in runtime.transports] == [False]


async def test_a_second_turn_opens_a_session_of_its_own(runtime: McpRuntime) -> None:
    await runtime.run(SOURCE_READ_PROMPT)
    await runtime.run(SOURCE_READ_PROMPT)

    assert len(runtime.transports) == 2
    assert runtime.open_before_the_agent_ran == [True, True]
    assert [transport.is_running for transport in runtime.transports] == [False, False]


async def test_credential_reaches_transport_only(install_mcp: RuntimeFactory) -> None:
    runtime = await install_mcp(credential_mode="veupathdb_user")

    outcome = await runtime.run(SOURCE_READ_PROMPT)

    transport = build_mcp_toolset(
        catalog_record(credential_mode="veupathdb_user"),
        SENTINEL_TOKEN,
    ).client.transport
    _cursor, logged = await fetch_chunks_after(runtime.conversation_id, 0)
    written = json.dumps(outcome.chunks) + json.dumps(logged, default=str)
    carried = repr(await runtime.state()) + repr(runtime.contexts)

    assert runtime.handed == [SENTINEL_TOKEN]
    assert transport.headers == {"Authorization": f"Bearer {SENTINEL_TOKEN}"}
    assert SENTINEL_TOKEN not in written
    assert SENTINEL_TOKEN not in carried


async def test_an_unreachable_optional_source_leaves_the_turn_alone(
    install_mcp: RuntimeFactory,
) -> None:
    runtime = await install_mcp(declare_offline_source=True)

    outcome = await runtime.run(SOURCE_READ_PROMPT)

    assert _of_type(outcome.chunks, "error") == []
    assert [
        c["toolCallId"] for c in _of_type(outcome.chunks, "tool-output-available")
    ] == [
        SOURCE_READ_CALL_ID,
    ]
