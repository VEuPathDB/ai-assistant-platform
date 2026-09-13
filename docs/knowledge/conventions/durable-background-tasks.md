---
type: Convention
title: Durable background tasks
description: What a durable tool does to a turn, what the worker does with it, how progress reaches the thread, and what a host wires to run one.
tags: [assistant-core, durable-tasks, protocol]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# A durable tool is a deferred tool

A tool whose work outlives a turn is declared with `declare_durable_tool` and
decorated with `durable_tool(tool)`. At call time the decorator writes a
`background_tasks` row recording the pydantic-ai `tool_call_id` its result
answers, defers a job onto the host's queue, records a `DurableDeferral` on the
agent's deps, emits `data-background-task-started` and raises `CallDeferred`.

The row is written before the defer, because the worker reads the row by the
id the payload carries. A defer that raises or is cancelled therefore removes
the row again through `discard_background_task`, shielded from the
cancellation, and the deferral and the chunk are written after the defer
returns: a refused defer leaves no row, no deferral and no announcement, and
the queue's own error reaches the model, carrying a note when the removal
failed too. The removal reads a `pending` row only: a row the worker started
owns the chunks and the progress rows that name it.

The run ends with `DeferredToolRequests`. The graph node parks a
`PendingDurableCall` on the state beside `pending_approval`, and the turn
closes with `finishReason: "other"`. There is no `interrupt()` and no node
replay.

**One model step can call several durable tools.** The parked call carries a
`durable_calls` list, one `DurableCall` per deferred call, because pydantic-ai
needs a result for every call of the response the run re-enters.

# The worker's half

The worker runs the registered body, then:

1. persists the result on the `background_tasks` row,
2. appends `data-task-completed` to the thread's log,
3. opens a **new turn** on the thread carrying `DeferredToolResults` keyed by
   each parked `tool_call_id`.

That turn opens only when **every** task of the parked step has reported. An
earlier arrival writes its completion chunk and stops, its result waiting on
its own row. Nothing before the calls runs again; each tool's
`chunks_from_result` runs on that turn and rides the result's metadata, so its
summary and figure land beside the tool's output part.

The completion turn runs under the per-role picks the deferring request
carried, read back from `background_tasks.phase_overrides`, because the
request that made them is gone.

# Progress

Progress rides the thread's own log; there is no per-task stream.
`TaskProgressEmitter` writes every update to `task_progress` and fires
`pg_notify` on `task_progress:<conversation_id>`, and appends a **coalesced**
`data-task-progress` chunk to the thread: one reaches the log when the task
advances five percentage points, or after ten seconds of silence. A scoped
child emitter reports in a lane of its own, so a fan-out leaves one part per
lane.

# What a host wires

- `install_task_app(app, durable_queue=...)` - the procrastinate application,
  its schema and the queue durable jobs run on. The default is `durable`.
- `register_durable_jobs(app)` - one job per declared tool, on that queue.
- `register_durable_impl(tool, impl)` - the worker-side body, in the worker.
- `install_worker_context(build)` - the turn context a body reads.
- `install_completion_turn(run)` - the driver for the turn a finished task opens.
- `install_durable_job_context(ctx)` - optional; state the worker cannot
  re-derive.
- `install_assistant_registry(registry)` - so the completion turn resolves the
  thread's assistant.
- a `HeartbeatThread` started around the worker's run, writing on
  `worker_heartbeat_interval_seconds`.

Each of those has a `reset_*` in the same module for a process that
re-composes.

A worker consumes `worker_queues()`, which carries the queue the host named.
The periodic sweep is
`release_stalled_jobs`, registered by the host under
`RELEASE_STALLED_JOBS_TASK`; it fails every job no live worker holds and
settles what that job was doing.

# What the sweep settles

One releaser per job. The sweep runs on a schedule and takes no job lock, so
`_release_job` holds `advisory_lease("assistant_core.release_job:<job id>")`
across the settlement and the `finish_job` that follows it. The lease is a
session-level database lock on a connection of its own: a second sweep that
arrives while the first is still writing finds the name taken and does nothing,
and a sweep that stops releases the name to the next one.

A released `chat_turn:run` job gets its stream closed: `error`,
`data-turn-failed`, `finish` and `done`.

A released `durable:<tool>` job is settled in the worker's place, by
`settle_unfinished_task`, which reads the row and takes one of three cases:

- **closed** (`complete`, `failed`): the outcome stands. The parked call is
  answered with it and nothing else is written, because a settler can stop
  between closing the row and answering the call.
- **open with a result** (`result_ready`, `resuming`): the result is announced
  as `data-task-completed` and delivered, and the row closes when the turn
  returns. The dead worker may not have announced it, and a second announcement
  of one outcome is what a reader already tolerates.
- **open with nothing** (`pending`, `running`): the row fails with the reason,
  the failure is announced, and the parked call is answered with it.

The order a settlement writes in is therefore: take the lease, write the
outcome chunk, close the row, open the completion turn, release the job. Every
step before the last is safe to run twice, so a settler that stops hands a
half-done settlement to the next sweep.

# The beat and the window

`release_stalled_jobs` and `release_dead_turn` read
`worker_dead_heartbeat_seconds` to decide which workers are dead, and fail the
jobs those workers hold, live chat turns included. The beat that keeps a
worker out of that set is `assistant_core.tasks.heartbeat.HeartbeatThread`,
which writes from a thread of its own: procrastinate beats on the loop the
jobs run on, so a job that holds the loop stops the beat. `RuntimeSettings`
refuses a configuration that leaves fewer than three beats inside the window,
naming both fields.

# Carried state, and the credential in it

A worker inherits no context variable from the process that deferred the job.
A host subclasses `DurableJobState`, types every credential field
`CarriedSecret`, and installs a context whose `capture()` returns that model
and whose `restore(state)` puts it back around the body. The state masks its
credentials in a `repr`, and the body reads one with `get_secret_value()` at
the point of use.

**The turn that answers the call runs under the same carried state as the
body.** `_answer_and_settle` restores it around the completion turn on every
path that opens one: the body's result, the body's failure, and a settlement
the stalled-job sweep makes, which reads the state back off the job's stored
payload through `StalledDurableTask`. Every tool of that turn therefore reads
what the deferring call carried, and a durable call the turn makes captures the
same state again. One job enters `restore` twice, once for each scope.

The queue stores the payload as JSON, so the value crosses it in clear.
`register_durable_jobs` therefore calls `install_job_payload_redaction()`,
which scrubs every `job_context` value out of procrastinate's own log lines. A
host does not need a filter of its own for this field.

`setup_logging()` attaches the same scrub after it replaces the root handlers,
so either order of the two calls leaves it on the line the process emits. A
host that names its worker passes that name to `register_durable_jobs`,
because procrastinate writes the job line on a logger named after the worker.

# The chat-turn payload the sweep reads

The host owns the `chat_turn:run` payload, and the sweep reads two fields out
of it: `assistant_core.tasks.chat_turn.ChatTurnJobArgs` states them as
`payload.turn_id` and `payload.body.conversation_id`, in either casing, with
everything else ignored. A payload that does not fit is logged and its job is
still failed, so the lock releases and only the stream stays open.

# Adding a durable tool

1. `tool = declare_durable_tool(tool_name=..., estimated_duration_seconds=...,
   chunks_from_result=...)` in a module both processes import.
2. Decorate the agent-side tool with `@durable_tool(tool)` and register it in
   its toolset with `sequential=True`.
3. Write the body and `register_durable_impl(tool, body)` where the worker
   registers its bodies.

The job name is derived from the declaration, so there is no third string to
keep in step. See
[A durable tool is declared once](../decisions/a-durable-tool-is-declared-once.md).

# The wire

`PROTOCOL.md` section 6.1 states the suspended turn.
`data-background-task-started`, `data-task-progress` and `data-task-completed`
are the three chunks, and
`packages/assistant-client-ts/tests/conformance/durableTask.test.ts` gates the
consumer side of them.
