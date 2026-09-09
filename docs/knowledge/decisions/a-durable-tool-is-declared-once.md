---
type: Decision
title: A durable tool is declared once
description: declare_durable_tool returns the value the decorator, the procrastinate job and the worker body all read, so the three strings that had to match become one.
tags: [assistant-core, durable-tasks, seams]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# The question

A durable tool used to be named three times: the decorator on the agent-side
tool, the registration of the worker-side body, and the `@app.task(name=...)`
that declares the job. The three lived in three modules and in two processes.
A typo in any one of them produced a job the worker answered with "unknown
task", at run time, on a user's turn.

# What was decided

`assistant_core.tasks.declaration.declare_durable_tool` takes the name once
and returns a `DurableTool`. That value is what everything else takes:

- `durable_tool(tool)` decorates the agent-side tool.
- `register_durable_impl(tool, impl)` binds the worker-side body.
- `register_durable_jobs(app)` walks the declared tools and declares one
  procrastinate job per tool, on the queue and under the name the declaration
  derives.

So the job name is derived, never written, and the two registrations take a
value rather than a string. A registration that names a tool this process did
not declare raises `UndeclaredDurableToolError` at registration time, naming
the tool and listing the declared ones. Registration happens at import, so the
refusal lands when the process starts rather than when a user asks.

The declaration also records the `DurableToolSpec` the answering turn reads,
so the chunk builder a tool's result carries is part of the same statement.

# What was rejected

**One call that also takes the body.** The agent-side decorator runs in the
process that serves requests and the body runs in the worker; a single call
would drag the worker's imports into the API process. Two calls over one
value keep the split and still write the name once.

**Keeping the strings and adding a test that walks the registry.** A test
finds the drift after it is written; a value cannot drift. The test that walks
the registry stays, because it proves the derivation.

# Anchor

`packages/assistant-core/tests/unit/tasks/test_tool_declaration.py`: a
declaration names its job, a second declaration of one name is refused, a body
registered under an undeclared value is refused with the sentence that says
what to pass, a hand-built copy with another budget is not the declared tool,
and every declared tool gets a job of the matching name on the durable queue.
