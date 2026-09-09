---
type: Decision
title: A tool source's session belongs to the turn, and the turn's driver opens it
description: ResolvedToolSources is an async context manager entered around the whole drive, so every declared MCP source is built, wrapped, opened and closed inside one turn. Letting the assistant's graph own the entry was rejected because a graph that raises leaks the session, and relying on pydantic-ai's per-run entry was rejected because a turn with several agent runs would open a connection per run.
tags: [assistant-core, mcp, lifecycle, turns]
generated: { by: claude-code/opus-5, at: 2026-08-24T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/mcp/resolution.py` holds `ResolvedToolSources`, an async
context manager. Entering it resolves every declaration the assistant made
into a wrapped, credentialed toolset and opens each session; leaving it closes
every session it opened, in reverse order, whatever happened in between. The
turn's driver enters it before it builds the turn context and leaves it after
the drive returns, so the map of ready toolsets reaches the assistant through
`TurnContextRequest.tool_sources` and lives exactly as long as the turn.

The admitted set the resolution reads is the one the host installed
(`admitted-tool-sources-are-installed-by-the-host.md`); it is a default, not an
argument the driver supplies, so no turn ever names a server.

Three library facts force the scope. `MCPToolset` takes its credential at
construction and bakes it into the transport, so a per-user credential cannot
be attached to a longer-lived object
(`pydantic_ai/mcp.py:868-1030`, `_build_transport` at `:1647-1693`). The
toolset is reference-counted: `__aenter__` opens the session only on the first
entry and `__aexit__` closes it only on the last (`:1165-1252`, `:1254-1268`,
the counter at `:856`, the `is_running` reading at `:1128-1131`). And an agent
run opens the toolsets it was given for its own duration and closes them again
(`pydantic_ai/agent/__init__.py:1868`).

# What was rejected

**The assistant's graph owns the entry.** The graph factory already builds the
agents, so it could open the sessions where it uses them. It was rejected
because a graph that raises leaves them open: the runtime would leak one
connection per failed turn, and the leak would be invisible until a deployment
ran out of sockets. The entry would also be written once per assistant, so a
second assistant is one forgotten `finally` away from the same leak, and the
platform would have no single place that states when a credential dies.

**Relying on the per-run entry pydantic-ai already does.** It is real, and it
is not enough. It is scoped to one agent run, so PathFinder's turn - a Lead
plus its phase sub-agents - would open and close a session per run against the
same server. It also never sees a turn that fails between runs.

# The consequence, stated

A source the assistant marked `required=False` that does not resolve is absent
from the map and the turn proceeds without it; a `required=True` source raises
`ToolSourceUnavailableError` from the entry, before the turn context exists, so
the turn fails before it spends a model call. Sources that already opened are
closed on that path.

# Anchor

`assistant_core/mcp/resolution.py`, pinned by
`packages/assistant-core/tests/unit/mcp/test_resolution.py` and
`tests/integration/mcp/test_in_process_server.py`: a turn measured at its own
edges holds an open session, the session is closed once the scope ends, and a
second turn opens one of its own.
