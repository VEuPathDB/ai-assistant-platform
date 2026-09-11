---
type: Convention
title: Embedding the runtime in a host
description: The three endpoints PROTOCOL.md specifies, the runtime call each one makes, the order a chat handler runs, the installs a worker makes before its first job, and the errors a host maps onto status codes.
tags: [assistant-core, protocol, host-integration]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

The runtime serves no HTTP and depends on no web framework.
`PROTOCOL.md` specifies three endpoints; a host writes them, and each one is a
call into this package. This page is the map between the two. It names no
application: everything below is in `assistant_core`.

# The two reads

| Endpoint | What the handler calls |
| --- | --- |
| `GET <thread>/events?after=<cursor>` | `conversation.authz.assert_owner(session, conversation_id, user_id)`, then `conversation.event_stream.iter_sse(conversation_id=..., after=...)` |
| `GET <thread>/events/snapshot` | `assert_owner`, then `conversation.event_stream.fetch_snapshot_chunks(conversation_id)`, which answers an `EventsSnapshot` |

`iter_sse` yields whole SSE frames, terminator included, and ends at the `done`
that closes the turn it attached to. The response carries
`text/event-stream` and the headers of
`conversation.vercel_adapter.VERCEL_AI_DSP_HEADERS`.

A tail with nothing to follow is a choice the host makes, not the runtime:
`conversation.event_stream.latest_event(conversation_id)` says whether the
newest chunk closed a turn, and `tasks.service.has_active_task` whether a
durable task will write more.

# The one write

`POST <api-root>/chat` starts a turn and answers with a tail. The handler runs
this order.

1. **Resolve the assistant.**
   `registry.resolve_turn_assistant(registry=..., conversation_id=..., requested_id=...)`
   reads the thread's row and answers the spec the turn runs under. A thread
   that does not exist yet takes the requested assistant or the registry's
   default.
2. **Run the identity gate.** `spec.identity_gate` when the spec declares one.
   It runs before the job is deferred, so a turn a caller may not open never
   reaches the worker.
3. **Open the thread.** The host creates or reads the row with
   `persistence.repositories.conversation.ConversationRepository`, stamping
   `assistant_id` with the spec's id. The row is the authority: a concurrent
   first turn can create the thread under another assistant between the
   resolve and the insert, so a host that finds another id there refuses the
   turn the way `AssistantMismatchError` is refused.
4. **Stop the turn in flight.** `conversation.cancellation.cancel_in_flight_turn`.
5. **Screen the user's text**, when the deployment screens it:
   `capabilities.input_screening.UserInputScanner`, whose refusal is
   `ScreeningRejectionError`.
6. **Append the user's message.**
   `persistence.repositories.message.MessagesRepository.insert_message` writes
   the turn's metadata row, and
   `conversation.event_writer.append_user_message_once` writes the envelope a
   client rebuilds its thread from. The second call is a no-op for a message
   id the log already carries, so a regenerate leaves one message.
7. **Read the tail's baseline.**
   `conversation.event_stream.latest_turn_boundary(conversation_id)`, before
   the job exists.
8. **Say the turn is queued.** `conversation.event_writer.ChatEventWriter`
   writes `graph.stream_events.turn_status_event(label=...)`, so the status
   can never land after the worker's first chunk.
9. **Defer the job.** `tasks.chat_turn.defer_chat_turn(conversation_id=...,
   payload=...)` puts one job on the runtime's chat-turn queue, locked on the
   thread id, because every turn of one thread writes one checkpoint thread.
   The payload is the host's; `tasks.chat_turn.ChatTurnJobPayload` states the
   two fields the runtime reads back out of it, and a payload without them is
   refused before the job exists. The host registers the body of
   `tasks.names.CHAT_TURN_TASK` on its own procrastinate application, because
   the body drives the host's turn driver.
10. **Answer with a tail.** `iter_sse(conversation_id=..., after=<the baseline
    of step 7>)`.

Spend is the host's decision on the runtime's count: `quota.get_current(session,
user_id, limit_usd=...)` takes the budget as an argument, and what a caller at
the limit is told is the host's.

# The worker

Turns run in a worker process, not in the process that serves the write. The
worker installs the seams before it consumes its first job, because a
declaration resolves when a job runs and not when the module is imported.

| Install | What it gives the runtime |
| --- | --- |
| `tasks.app.install_task_app(app)` | The procrastinate application every deferral opens. Also needed in the process that serves `POST /chat`. |
| `registry.install_assistant_registry(registry)` | The assistants, to work that carries no request. |
| `tasks.runner.install_worker_context(build)` | The turn context a durable body reads. |
| `tasks.runner.register_durable_jobs(app)` | One procrastinate job per declared durable tool. |
| `tasks.completion_turn.install_completion_turn(run)` | The turn a finished task opens. |
| `tasks.job_context.install_durable_job_context(ctx)` | State a worker cannot re-derive, such as a carried credential. |
| `mcp.admission.install_admitted_sources(admitted)` | The tool servers this deployment admits. |

A worker consumes the queues `tasks.names.WORKER_QUEUES` lists, and writes its
beat with `tasks.heartbeat.HeartbeatThread`, which is what the stalled-job
sweep reads. A missing install is not reported at start: it raises when the
first job needs it, as `TaskAppNotInstalledError`,
`RegistryNotInstalledError`, `WorkerContextNotInstalledError` or
`CompletionTurnNotInstalledError`.

The turn's own driver is the host's: it reads `spec.turn_prologue` before the
graph, `spec.turn_cancel` on a turn the user stopped, and `spec.turn_epilogue`
after the graph, and it writes every chunk through a `ChatWriter`.

# The refusals

No error here names an HTTP status. A host maps them.

| Error | What it means |
| --- | --- |
| `errors.ConversationNotFoundError` | No such thread, or one the caller may not see |
| `errors.ConversationForbiddenError` | The thread belongs to another user or another application |
| `errors.TurnStillRunningError` | The worker did not close the turn inside the stop window |
| `registry.UnknownAssistantError` | The request names an assistant this deployment does not serve |
| `registry.AssistantMismatchError` | The request names an assistant other than the thread's |
| `capabilities.input_screening.ScreeningRejectionError` | The screener refused the user's text |
| `mcp.resolution.ToolSourceUnavailableError` | A source the assistant declared as required did not resolve |

`errors.AssistantCoreError` is the base of the first three.
