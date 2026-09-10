---
type: Backlog
title: An unadmitted optional tool source warns on every turn
description: A source an assistant declares as optional but the deployment does not admit is logged at WARNING each time a turn resolves its tool sources. The fact is static for the deployment, so one INFO line at admission time would say the same thing once.
tags: [mcp, logging, runtime]
generated: { by: claude-code/fable-5.1, at: 2026-09-10T00:00:00Z }
verified: { by: claude-code/fable-5.1, at: 2026-09-10T00:00:00Z }
status: open
---

# What is missing

`src/assistant_core/mcp/resolution.py::ResolvedToolSources._open` logs
`Tool source did not resolve` at WARNING whenever a declared source has no
admission record, then continues when the declaration is optional. A host that
declares an optional source it does not admit in one deployment (an e2e stack
with no service token for it) therefore writes one warning per turn for a
condition that does not change between turns and that the assistant's
instructions already tolerate.

# What would close it

Report an unadmitted optional source once, at INFO, when the admitted set is
installed or on the first turn that resolves it, naming the source and
"not admitted in this deployment"; keep WARNING for a required source, whose
turn is refused. A unit test that resolves the same optional source twice and
reads one log record.
