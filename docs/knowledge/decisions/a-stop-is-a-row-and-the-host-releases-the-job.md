---
type: Decision
title: A stop is a row, and the host releases the job
description: Stopping a turn writes a chat_turn_cancellations row the running worker polls, and a turn whose worker is already dead is ended by failing the job that holds it.
tags: [assistant-core, cancellation, persistence, seams]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.conversation.cancellation` owns the stop protocol.
`cancel_in_flight_turn` reads the newest chunk of a thread's log, and when
that chunk does not close the stream it writes a `chat_turn_cancellations`
row for that turn. The worker running the turn polls
`turn_is_cancelled(conversation_id, turn_id)` and closes its own frame. The
table is the runtime's and joins its migration chain.

The write also emits `pg_notify` on `chat_turn_cancel:<conversation_id>`,
carrying the turn id as its payload. The channel is not on the wire, so
`PROTOCOL.md` does not name it: it is stated here so a host that wants to
listen rather than poll knows the name it would listen on. No listener exists
today; every reader of the stop polls the row, and the notification is the
open half a host may take instead.

`stop_turns_and_wait` and `cancel_active_turn` release the job themselves,
through `assistant_core.tasks.maintenance.release_dead_turn`. A worker silent
longer than `worker_dead_heartbeat_seconds` never reads the row, so its job is
failed and its stream closed from outside. This was a callable the host passed
in per call while `background_tasks` was still the host's; the durable-task
move brought the queue into this package, so the argument went and the release
is an implementation detail.

`stop_turn_before_delete` waits for the closing chunk and raises
`TurnStillRunningError` when it does not come, because a worker appends to a
thread until it reads the stop and deleting the row under it breaks every
write that follows. Its `timeout_seconds` is an argument: how long a caller
waits for a worker is the caller's patience, not the runtime's.

# What was rejected

**Importing the host's maintenance job.** The application these functions came
from called its own `release_dead_turn` directly. That would have been an
import of the host from the runtime, which the package boundary refuses. The
release moved here instead, with the queue it needs
(see [The runtime defers onto the host's queue](the-runtime-defers-onto-the-hosts-queue.md)).

**Cancelling through LISTEN/NOTIFY alone.** A notification reaches a live
listener and nobody else, so a worker that reconnects after a restart would
miss the stop. The row is the durable statement and the notification is only a
prompt to read it sooner.

**Naming the channel in `PROTOCOL.md`.** The document states what crosses the
wire between a host and a client. The channel is between two of the host's own
processes, so it belongs to this bundle.

# Anchor

`packages/assistant-core/tests/integration/conversation/test_stop_protocol.py`:
a stop writes the row the worker reads, a closed turn has nothing to stop, the
newest open turn is the one stopped, a caller of another application is refused
and releases no job, the owner's stop fails the job a dead worker held, a
worker that never closes is reported pending, a stop on a dead worker's thread
closes the stream it left open, and the wait ends as soon as the closing chunk
lands.
