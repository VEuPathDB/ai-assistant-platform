---
type: Decision
title: A host-started task writes nothing to the thread
description: A durable task a host starts has no parked call, defers under a lock the host names, writes no chunk to the thread's log, opens no completion turn and is not an active task. A synthetic turn holding the started chunk, the thread's lock, and one short job per poll were rejected.
tags: [assistant-core, durable-tasks, protocol, seams]
generated: { by: claude-code/opus-5.5, at: 2026-09-24T00:00:00Z }
verified: { by: claude-code/opus-5.5, at: 2026-09-24T00:00:00Z }
status: stable
---

# What was decided

Some long work starts from a host's own interface, not from a model call: a
button that uploads a file and then waits on a remote install. The runtime runs
it as a durable task with no turn around it.

- `declare_durable_tool(..., host_started=True)` marks the declaration, and
  `start_host_task(tool, conversation_id=..., user_id=..., kwargs=..., lock=...)`
  starts it. The row's `tool_call_id` is NULL and nothing is parked.
- The job defers under the lock the host names. It never takes the thread's id:
  `start_host_task` refuses that lock.
- No channel a reader of the thread listens on is notified. Settling a row
  writes the row and nothing else.
- The body's progress reaches `task_progress` and its notification only. The
  runner records the outcome on the row and writes no
  `data-background-task-started`, `data-task-progress` or
  `data-task-completed`.
- No completion turn opens, and `has_active_task` does not count the row.
- `durable_tool` refuses a host-started declaration at decoration, and
  `start_host_task` refuses one without the flag.
- The stalled-job sweep settles a host-started row without a chunk or a turn.

`PROTOCOL.md` is unchanged, because nothing new reaches the wire. A host shows
the task from the task listing it already reads (`tasks.queries`).

`has_active_task` reads `tool_call_id IS NOT NULL`. The question it answers is
whether a turn waits on the task, and a NULL call id says no turn does. The
query runs in the process that serves the tail, which may declare no tool, so
the row answers it and the declaration registry does not. A `host_started`
column was not added: it would be a second fact on the row that could
contradict the first, and it would need a migration for no new information.

# What was rejected

**Writing the task's card into the thread log**, as a synthetic turn that holds
only a `data-background-task-started`. The transcript would carry a message the
checkpointed history does not, and the next operation on the thread (a fork, a
revert) would copy or cut a turn nobody took. Writing the progress and the
outcome without a turn is no better: they land in the gap after whichever turn
came last, and a reducer that follows `PROTOCOL.md` section 6.1 attaches the gap
to that turn's message, under an unrelated answer. The host's own task rows
give the same visibility.

**Holding the thread's lock like a durable call.** A durable call's job takes
the thread's id because its completion turn writes the thread's checkpoint. A
host-started body writes no checkpoint, and a task that polls for tens of
minutes under that lock queues every chat turn of the thread behind it.

**Re-deferring one short job per poll** (`schedule_in`), so no worker slot is
held while the task waits. The runtime runs one body per task row. A successor
job that inherits the row, its progress and its carried state is a second
runtime concept, with its own sweep case. One sleeping coroutine per active
task costs less while a host starts few of them. This choice is revisited if a
host needs many such tasks at once.

# Anchor

`packages/assistant-core/tests/integration/tasks/test_host_task.py`: the row
has a NULL `tool_call_id`, the job's lock in `procrastinate_jobs` is the one
the host named, a success completes the row and a failure records the raised
text, no completion turn opens and the thread has 0 events, and
`has_active_task` is False while `list_task_rows` returns the running row, and
no listener of the thread's channels hears the task.
`tests/integration/tasks/test_maintenance.py` covers the three sweep cases for
a host-started row. `tests/unit/tasks/test_durable_deferral.py` and
`tests/unit/tasks/test_host_task_refusal.py` cover the three refusals.
