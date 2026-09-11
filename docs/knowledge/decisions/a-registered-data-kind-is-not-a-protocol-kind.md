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

The kinds that prompted the question were `data-memory-retrieved`,
`data-scratchpad-updated` and `data-user-question-answers`. Which of them the
document names is settled by what emits them, not by what registers them: a
builder something in this repository calls is the runtime's, and a builder
whose only caller is a host's code is the host's.
`assistant_core.scratchpad.tools` calls `scratchpad_updated_event` four times,
so `data-scratchpad-updated` is a core kind and the table names it; nothing
here calls `memory_retrieved_event`, so `data-memory-retrieved` is registered
by the assistant that recalls memories. `data-lead-usage`,
`data-sub-agent-call` and `data-sub-agent-step` left the core registry under
the same rule, and
`tests/unit/conversation/test_data_part_table.py` is the gate: every kind a
call site here emits is in the table.

# What was rejected

**Making `isKnownChunkKind` consult the captured data-part list.** Rejected: it
drops an assistant's registered kinds from the stream.

**Adding every one of the three kinds to `PROTOCOL.md`.** Rejected: the
document names what something here emits. A kind whose builder only a host
calls describes that host's shape, and a second consumer implementing the
document would be implementing a kind no deployment but one produces.

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
