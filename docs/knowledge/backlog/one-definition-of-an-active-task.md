---
type: Backlog
title: Two definitions of an active durable task
description: has_active_task reads three statuses and the repository publishes four, so a result_ready task is active to one reader and finished to the other, and a host's rail carries a third copy.
tags: [assistant-core, durable-tasks, persistence]
generated: { by: claude-code/opus-5, at: 2026-09-12T00:00:00Z }
status: proposed
---

# Two definitions of an active durable task

**What I did.** Read every reader of a `background_tasks` row's status while
making the stalled-job sweep settle a durable task.

**What I got.** `assistant_core/tasks/service.py::_ACTIVE_TASK_STATUSES` is
`{"pending", "running", "resuming"}`. `persistence/repositories/background_tasks.py`
publishes `ACTIVE_TASK_STATES = ("pending", "running", "resuming", "result_ready")`
and `list_active_for_conversation` reads that one. PathFinder's tasks rail keeps a
third copy of the three-state set.

**Why that's wrong.** A task at `result_ready` is finished work waiting for its
completion turn. `has_active_task` answers `False` for it, so a thread's tail can
close while the runtime still owes the thread a turn; `list_active_for_conversation`
answers `True` for the same row. The sweep now decides on the four-state tuple, so
the two definitions disagree on the row the sweep is most likely to meet.

**Why it happens.** The three-state set was written for the tail's question ("is
anything going to write?") and the four-state tuple for the worker's ("is the worker
finished with this row?"), and neither names the other.

**Fix.** Publish the two questions as two named tuples on the repository, delete
`_ACTIVE_TASK_STATUSES`, and have `has_active_task` read the one it means. Then a
host's own copy can cite a name instead of repeating a list.

**What you'd get.** One place answers what a status means, and a `result_ready`
row reads the same to every reader.
