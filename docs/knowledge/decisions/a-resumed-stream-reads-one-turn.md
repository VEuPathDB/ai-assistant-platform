---
type: Decision
title: A resumed stream reads one turn, and the transport holds the rest
description: The AI SDK builds one message per stream and seeds it with the message the client already holds, so DurableChatTransport ends a resumed stream at a `start` that opens another turn and serves the rest to the next resume; merging the continuation into the suspending message, a second HTTP tail, and giving `data-background-task-started` an `id` were all rejected.
tags: [chat, protocol, client, durable-tasks]
generated: { by: claude-code/opus-5, at: 2026-08-31T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`ai@6` reads one assistant message per stream. `AbstractChat.makeRequest` seeds
that reader with `createStreamingUIMessageState({ lastMessage })`, so a resumed
stream starts from the message the client already holds, and the reader's
`start` case only renames it. A tail that carries a suspended turn's gap and
then the continuation turn therefore ends with the continuation holding every
part of the turn before it.

`DurableChatTransport` ends a resumed stream at a `start` chunk that names a
message other than the one the stream is building. It keeps the frame iterator,
so the rest of the tail is served to the next resume with no second request,
and it reports the message id it stopped at. `resumeDurableThread` opens that
message on the chat before resuming again, so each turn is read into a message
that exists to receive it. PROTOCOL 1.5.2 states the reader rule in section 9.

# Why not merge the continuation into the suspending message

Dropping the boundary `start`'s `messageId` keeps one message and is three
lines. It was rejected because the live thread would then disagree with the
same thread reloaded: `reduceSnapshot` splits at every `start`, so a reload
shows two messages where the live read showed one, and the continuation turn's
`start` metadata (its phase, its model, its instant) would overwrite the
suspending turn's instead of standing beside it.

# Why not re-request the tail after the boundary

Persisting the cursor at the boundary and letting the next resume fetch
`after=<that cursor>` needs no buffer. It was rejected because the tail answers
`204` once the continuation turn is over and no task is active, so a turn that
finished between the two requests would be lost, and the client would hold an
opened message the log never filled.

# Why not give the chunk an id to reconcile on

`data-background-task-started` carries no `id`, and section 5.2's
reconciliation would collapse two copies if it did. It was rejected because
nothing re-sends it: the frame reaches the client exactly once, and the second
part is a copy the reader made. An `id` would also be a protocol change made to
work around a reader, which is what section 9 now states instead.
