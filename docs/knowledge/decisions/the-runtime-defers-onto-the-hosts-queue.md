---
type: Decision
title: The runtime defers onto the host's queue
description: The host opens the procrastinate application and its schema and installs it; the runtime owns the deferral, the parked call, the progress emitter, the beat, the completion turn and the redaction of what a job carries, and reaches the host through four installed seams.
tags: [assistant-core, durable-tasks, seams, persistence]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

The durable-task subsystem is the runtime's, and the queue it runs on is the
host's. `procrastinate` is a dependency of this package
(see [The runtime owns its task tables](the-runtime-owns-its-task-tables.md)),
but the runtime never builds a connector, applies a schema or starts a worker.
The host builds `procrastinate.App` and calls `install_task_app(app)`; the
runtime defers onto it and manages the jobs it named.

Four seams carry what the runtime cannot know, each installed once per
process:

| seam | what a host supplies |
| --- | --- |
| `install_task_app` | the procrastinate application, its schema and the name of the durable queue |
| `install_worker_context` | the turn context a durable body reads, built from the thread |
| `install_completion_turn` | the driver that runs the turn a finished task opens |
| `install_durable_job_context` | state the deferring process holds that the worker cannot re-derive |

Each seam has a matching `reset_*` in the same module, so a process that
re-composes installs again instead of writing the holder's private field.

The runtime also declares the names the host wires:
`assistant_core.tasks.names` holds the queue names, `chat_turn:run`,
`maintenance:release_stalled_jobs` and `durable_job_name`. A host's periodic
registration reads them rather than repeating the strings, and its worker
subscribes to `assistant_core.tasks.app.worker_queues()`, which carries the
durable queue the host named
([the host names the durable queue](the-host-names-the-durable-queue.md)).

The job context is the seam that keeps a product's credential out of this
package. A host subclasses `DurableJobState`, types every credential field
`CarriedSecret`, and implements `capture()` and `restore(state)`; the payload
carries that model and the runner validates it back into the host's own type
before restoring it around the body. The runtime's default captures nothing.

The state masks itself in a `repr`, and the worker reads a credential back
with `get_secret_value()` at the point of use. The queue itself stores JSON,
so the value crosses it in clear and procrastinate would print it in
the line it logs when a job starts. The runtime owns the field, so the
runtime scrubs it: `register_durable_jobs` calls
`install_job_payload_redaction()`, which replaces every `job_context` value on
a procrastinate log record. A host needs no filter of its own for this field.

The heartbeat is the same shape of coupling. `worker_dead_heartbeat_seconds`
decides which workers are dead and which jobs are failed under them, so the
beat that answers it lives here too: `assistant_core.tasks.heartbeat` writes
it and `RuntimeSettings` refuses a configuration that leaves fewer than three
beats inside the window. The host still builds the `Worker` and starts the
thread.

The host's `chat_turn:run` payload is a contract, because the stalled-job
sweep reads two fields out of it to close the stream a killed turn left open.
`assistant_core.tasks.chat_turn` publishes the shape:
`ChatTurnJobArgs.payload.turn_id` and `.payload.body.conversation_id`, in
either casing, everything else ignored. A payload that does not fit is logged
and its job is still failed, so the lock releases.

`assistant_core.registry.install_assistant_registry` is installed for the same
reason: the completion turn resolves the thread's assistant with no request to
read one from.

# Taking this release

The durable job's kwargs changed shape: `veupathdb_auth_token` went and
`job_context` arrived. The job names did not change, so an old job queued
under the previous signature reaches the new worker and fails on an unexpected
keyword argument. **Drain the durable queue before the deploy that takes this
release.**

The queue's name became the host's in a later release. `WORKER_QUEUES` is gone
and `worker_queues()` answers in its place, so a host that names the queue it
already runs on keeps every queued job and drains nothing.

# What was rejected

**The runtime building the procrastinate application.** It would own a
connection string, a pool and a schema migration a host already runs, and a
host with its own queue could not install it.

**Naming the host's credential on the payload.** The payload used to carry one
product's authentication token by name, and a host-side log filter matched on
that name to keep it off stdout. `job_context` is a typed state model the host
subclasses and the runtime never reads a field of, and the scrub matches the
runtime's own field name instead of a product's.

**Keeping the credential off the queue by storing it on the task row.** It
would move the value from one table to another and buy nothing at rest, at the
cost of a column, a second read per call and a row that holds a live
credential with no expiry.

**Passing the four seams per call.** The runner is the body of a job the
runtime itself registers, so there is no call site to pass them at. They are
installed at composition, like the admitted tool sources.

# Anchor

`packages/assistant-core/tests/integration/tasks/`: a turn parks on a durable
call, the job the decorator deferred is the job the queue holds, the worker
runs the body with the state the call captured, and the completion turn
answers with the result. `tests/unit/tasks/test_seams.py` states what a
process that installed no queue, no turn driver, no worker context and no
registry is told, and what each reset puts back.
`tests/unit/tasks/test_job_context_secrets.py` asserts that the captured state
masks its credential and that the line procrastinate formats for a real
payload carries none of its bytes. `tests/unit/tasks/test_heartbeat.py` states
the beat and the refusal of a beat too slow for the window.
`tests/integration/tasks/test_maintenance.py` states what a chat-turn payload
the contract does not fit gets.
