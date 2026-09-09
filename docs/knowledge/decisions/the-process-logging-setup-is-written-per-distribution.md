---
type: Decision
title: The process logging setup is written once per served distribution
description: The runtime and the MCP tool server each configure structlog in their own module, and the two copies are reconciled by hand, because the two distributions share no dependency edge and a shared module would create one.
tags: [assistant-core, logging, packaging]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/platform/logging.py::setup_logging` and the MCP tool server's
`veupathdb_mcp/logging_setup.py::setup_logging` are two files with the same
processor chain, the same `ProcessorFormatter` wiring and the same JSON or
console switch. They stay two files.

The copies are reconciled by hand against two invariants. The process holds one
root handler: the handler is assigned onto the root logger rather than appended,
so a second call to `setup_logging` logs each line once. A served logger reaches
that handler: uvicorn ships its loggers with propagation off, so each one has
propagation flipped on and its own handlers dropped.

The runtime's copy keeps what the MCP server's has no use for: the request,
application and OpenTelemetry processors, and the settings source a host
installs.

# What was rejected

**One shared module.** It is the obvious de-duplication, and it was rejected
because `assistant-core` and `veupathdb-mcp` depend on each other in neither
direction. A shared module would have to live in one of them, and the loser
would gain a dependency on the whole of the other for fifty lines of process
setup.

**A fifth micro-distribution to hold it**, as with the settings-source scaffold.
Rejected for the same reason recorded there: a package, a version, a tag and a
release for fifty lines that change once a year buys less than it costs.

# Anchor

`packages/assistant-core/tests/unit/platform/test_setup_logging.py`: a second
call leaves one root handler, and the served loggers reach it.
