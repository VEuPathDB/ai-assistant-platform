---
type: Decision
title: The host names the queue its durable work runs on
description: install_task_app takes the durable queue name, the runtime's default is "durable", and worker_queues() is what a worker subscribes to. Renaming the constant alone, and keeping one host's phase word as the default, were both rejected.
tags: [assistant-core, durable-tasks, seams, naming]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

# What was decided

`install_task_app(app, durable_queue=...)` names the queue durable tool jobs
are deferred onto, for the whole process. `assistant_core.tasks.app` answers it
back as `durable_task_queue()`, the decorator and the job registration read it,
and `worker_queues()` is the tuple a worker subscribes to. The runtime's
default is `DEFAULT_DURABLE_TASK_QUEUE`, which is `"durable"`: it says what
runs on the queue, and it names no product
([the runtime's stored defaults name no product](the-runtime-defaults-name-no-product.md)).

Every process of one deployment names the same queue, because a job deferred
onto one queue is consumed by a worker that subscribes to it and by no other.
A deployment that keeps a queue it already runs jobs on states that name and
drains nothing.

# What was rejected

**Setting the constant to `"durable"` and leaving it constant.** It fixes the
name and takes the choice away: every deployment with jobs already queued under
the old name must drain before the deploy that takes the release, and a
deployment whose operators run durable work on a queue of their own still
cannot say so. The queue is the host's; its name is too.

**Keeping `"verification"` as the runtime's default.** It is one assistant's
phase word. It misdescribes the queue for every deployment, the one that named
it included, because what runs there is every durable tool. An operator
triaging long-running tool jobs looks for a queue named after them.

**Reading the name from the environment.** The runtime reads no configuration
of its own
([the admitted tool sources are installed by the host](admitted-tool-sources-are-installed-by-the-host.md));
a value the runtime would read from the environment is a value no host can
state in code and no test can pin.

# Anchor

`packages/assistant-core/tests/unit/tasks/test_seams.py`: a process that named
no queue defers onto the default and subscribes to it, a host's name reaches
both `durable_task_queue()` and `worker_queues()`, the reset puts the default
back, and `tasks.names` exports neither of the two names a worker imported
before, so a worker written against them fails at import rather than
subscribing to a queue nothing defers onto. `tests/unit/tasks/test_tool_declaration.py` registers every
declared tool on the host's queue, and
`tests/integration/tasks/test_durable_arc.py` reads that name back off the
deferred job.
