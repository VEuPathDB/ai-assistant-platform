---
type: Backlog
title: The age timeout releases a durable job a live worker is still running
description: release_stalled_jobs asks for jobs past worker_stalled_job_timeout_seconds whatever their worker says, so a durable body that legitimately runs past the timeout has its row failed under a worker that then writes its result onto it.
tags: [assistant-core, durable-tasks, jobs, reliability]
generated: { by: claude-code/opus-5, at: 2026-09-12T00:00:00Z }
status: proposed
---

# The age timeout releases a durable job a live worker is still running

**What I did.** Read the two selections `release_stalled_jobs` merges, after the
sweep learned to settle a durable job.

**What I got.** `_dead_workers_jobs` names a worker by its heartbeat, so a live
worker's job is never in that set. `_long_running_jobs` names a job by the age of
its `started` event alone, with `worker_stalled_job_timeout_seconds` (default 3600),
whatever the worker says. Both sets are released the same way.

**Why that's wrong.** A durable body is the kind of work that legitimately runs for
hours. When the age timeout releases one, the sweep fails its row, announces
`data-task-completed` with a failure and answers the parked call; the worker that is
still running then writes `mark_result_ready` onto that row and announces a second,
contradicting outcome. The user reads a failure, then a success, for one call, and
the run that was answered with the failure has already moved on.

**Why it happens.** One number answers two questions: "is anything running this?"
and "has this run too long?". The heartbeat answers the first. The age timeout was
written for a chat turn, whose ceiling is a turn.

**Fix.** Decide what the age timeout means for a durable job. Either the durable
branch settles only what the heartbeat named dead and a long durable job is ended by
its own budget, or a released job is stopped on its worker before its row is failed.
This is a decision with a real alternative, so it is recorded as one when it is taken.

**What you'd get.** A long durable call ends once, with one outcome, and a worker
that is still running is never contradicted by the sweep.
