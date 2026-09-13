---
type: Backlog
title: A pending task row the queue holds no job for is settled by nobody
description: The row is committed before the defer, so a process killed between the two leaves a pending background_tasks row that the job-driven sweep cannot see and has_active_task answers True on for ever.
tags: [assistant-core, durable-tasks, persistence]
generated: { by: claude-code/opus-5, at: 2026-09-13T00:00:00Z }
status: proposed
---

# A pending task row the queue holds no job for is settled by nobody

**What I did.** Traced one durable call from `tasks/decorator.py` to
`tasks/maintenance.py`. `create_background_task` commits a row with
`status="pending"` through a unit of work of its own, and `job.defer_async`
runs two statements later on the host's procrastinate application.

**What I got.** A process that stops between those two statements leaves the
row committed and no job deferred. `release_stalled_jobs` enumerates jobs and
nothing else: `get_stalled_jobs(seconds_since_heartbeat=...)` and
`get_stalled_jobs(nb_seconds=...)`, and `_settle_released_work` reaches
`settle_unfinished_task` only through a job's `task_kwargs`. No pass of the
sweep reads `background_tasks`, so the row stays `pending`.
`has_active_task` selects `status IN ('pending', 'running', 'resuming')` and
answers `True` on that thread for ever;
`list_active_for_conversation` lists the row for ever too.

**Why that's wrong.** A thread that owes no work reads as busy. A host that
asks `has_active_task` before it answers a reconnect opens a stream that never
receives a chunk, and a host that waits for `list_active_for_conversation` to
empty before it reads a turn's result waits until its own timeout. Neither ends,
because nothing will ever write the row again.

**Why it happens.** The row is committed before the defer, and only the
in-process handler in `tasks/decorator.py` removes it. That handler needs the
process: a `SIGKILL`, an out-of-memory kill, an eviction, or the loop teardown
that cancels the shielded removal all skip it.

**Fix.** Give the sweep a second pass over rows instead of jobs:
`release_orphaned_task_rows`, called from `release_stalled_jobs`, fails every
`background_tasks` row still `pending` whose `created_at` is older than a new
`RuntimeSettings` window and announces the failure. It answers no parked call,
because no call was ever parked for such a row, and it never reads a `running`
row, which `settle_unfinished_task` already owns through the job. The window
floor is the dead-heartbeat window, and it has to stay well above the gap
between the row and the defer so a live call is never swept.

**What you'd get.** A row a killed process left behind reaches `failed` one
window later, `has_active_task` answers `False`, and a host's reconnect and its
wait both end.
