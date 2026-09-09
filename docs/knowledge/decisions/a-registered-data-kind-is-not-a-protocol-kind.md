---
type: Decision
title: A data kind the document does not name still reaches the client
description: isKnownChunkKind accepts every data- prefixed kind, so an assistant that registers its own kinds keeps them. Gating data parts on the captured list was rejected: it would drop an assistant's own parts from the stream, which section 5.2 permits and this deployment relies on.
tags: [assistant-client, protocol, chunks]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

`isKnownChunkKind` answers true for every `data-` prefixed kind and, for the
rest, for the kinds `captured.json` names. `DurableChatTransport` gates the
stream on it, so an assistant's own data parts reach the reader and
`onUnhandledChunk` reports only a chunk that is neither.

The consequence is written down rather than removed: `onUnhandledChunk` cannot
fire for a data part. A host that wants to know about a kind it does not draw
compares its own renderer map against the kinds it receives, which is a
question about that host's renderers and not about the wire.

# Why

Section 5.2 says the runtime defines its data kinds and an assistant MAY
register more. A client that accepted only the documented kinds would drop
every kind an assistant registered: they would never reach the reducer, so the
parts would be missing from the message and the thread would render without
them. That is a data loss dressed as a strictness improvement.

The three kinds that prompted the question (`data-memory-retrieved`,
`data-scratchpad-updated`, `data-user-question-answers`) are not registered by
the runtime: `register_core_stream_parts` does not name them, so the document's
table does not either, and `assistant-core`'s own suite asserts that the table
equals the kinds the runtime registers. Adding them to the document would fail that assertion.

# What was rejected

**Making `isKnownChunkKind` consult the captured data-part list.** Rejected: it
drops an assistant's registered kinds from the stream.

**Adding the three kinds to `PROTOCOL.md`.** Rejected: the runtime registers
none of them, and the document's table is checked against that registry. A kind
belongs in the table when the runtime emits it.

# Accepted overlaps

Three shapes exist twice, and both copies are correct:

- **The snapshot envelope.** `core/snapshot.ts` types the protocol's snapshot;
  an application's generated API types describe the route that serves it. The
  route may stop being generated; the protocol shape may not.
- **The message-part union.** The protocol's union, the AI SDK's own, and an
  application's generated one describe three different contracts.
  `toTraceParts` is the conversion between the first two and exists for that.
- **`AssistantMessage.finishReason`, `errors` and `aborted`.** Section 6 states
  them, the core reducer fills them, and the SDK path never builds an
  `AssistantMessage`. They stay: the core and `./legacy` rings have readers this
  repository does not write.
