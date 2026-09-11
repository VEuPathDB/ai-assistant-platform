---
type: Backlog
title: The runtime's durable queue is named after one host's phase
description: DURABLE_TASK_QUEUE is "verification", a phase word from the one assistant built on this runtime, and it is exported in WORKER_QUEUES so every host's worker consumes a queue named for a workflow it does not have.
tags: [assistant-core, tasks, naming, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/assistant-core/src/assistant_core/tasks/names.py` and checked
what a host does with the constant.

# What I got

`tasks/names.py:3-4`:

```
# Durable tool jobs run here, so a long tool never blocks a chat turn.
DURABLE_TASK_QUEUE = "verification"
```

The three queues beside it are named for what runs on them: `CHAT_TURN_QUEUE =
"chat_turn"`, `MAINTENANCE_QUEUE = "maintenance"`, `DEFAULT_QUEUE = "default"`.
`DURABLE_TASK_QUEUE` is exported in `WORKER_QUEUES` at the bottom of the same
file, and a host passes that tuple straight to its worker
(`pathfinder: apps/api/src/pathfinder/jobs/worker.py`, `queues=list(WORKER_QUEUES)`).
The word is one assistant's phase name: `VERIFY` is a sub-agent role in the one
host, whose own instructions name a `verification` queue to drain before a
release.

# Why that is wrong

A second organisation's operator reads `verification` in its queue dashboard,
its worker logs and its procrastinate rows, and has no workflow by that name.
The queue actually carries every durable tool, verification or not, so the name
misdescribes what is on it for every deployment including the one that named
it. An operator triaging a backlog of long-running tool jobs looks for a queue
named after long-running tool jobs and does not find one.

# Why it happens

`DURABLE_TASK_QUEUE` in `tasks/names.py` holds a value from one host's phase
vocabulary rather than a name for the work the queue carries.

# Fix

Set `DURABLE_TASK_QUEUE = "durable"`. The constant is already the single point
of truth, so nothing else in the runtime changes. This is a breaking change for
a running deployment: a job already enqueued on the old queue is not consumed
by a worker that subscribes to the new one. Rides the next `assistant-core`
release, and the release notes state the drain. When PathFinder takes that tag
it drains the `verification` queue before it deploys the new worker, and it
updates the drain instruction it keeps for its own operators
(`pathfinder: CLAUDE.md`).

# What you would get

Every host's worker subscribes to a queue whose name says what runs on it, and
no deployment inherits another product's phase vocabulary in its operations.
