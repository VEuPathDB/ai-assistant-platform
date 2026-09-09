---
type: Decision
title: The client package has three rings, and the innermost one has no dependencies
description: packages/assistant-client-ts splits into a dependency-free protocol core, one AI-SDK-coupled transport module, and a legacy module for the task dialect the protocol does not define. React stays in the app. Publishing one module that imports the AI SDK everywhere was rejected, because a host that does not use the SDK would inherit it to parse a frame.
tags: [assistant-client, ws-v, protocol, sse, packaging]
generated: { by: claude-code/opus-5, at: 2026-08-23T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`packages/assistant-client-ts` publishes `@veupathdb/assistant-client` as three
entry points, and a consumer takes only the ring it needs.

**The core (`.`) has no runtime dependencies.** It is the whole of
`PROTOCOL.md`: the strict frame reader, cursor semantics, the chunk-to-message
reduction of section 9, the snapshot reader, the turn request body, and an
`AssistantClient` that reads a thread over SSE or by polling its snapshot. A
host in any framework can implement a client from this ring alone, which is
what the document claims a reader can do.

**The transport (`./ai-sdk`) depends on `ai`, and only it does.** `useChat`
takes a `ChatTransport`, and the base class that implements one is a class, not
a type, so a subclass is a real dependency. The dependency is declared as an
optional peer: a consumer that never imports `./ai-sdk` never resolves it.

**The task dialect (`./legacy`) is named for what it is.** The durable-task
progress endpoint frames `event: stream\ndata: <json>\n\n` and carries no
cursor. That is a third frame shape, and section 3 says a client must reject
any third shape - so the protocol's own reader refuses it, and a test asserts
the refusal.

**Amended at protocol 1.1.0: the ring is deprecated.** A durable task's whole
lifecycle is on the thread now, so the core ring reads everything this one
reads (`pathfinder: docs/knowledge/decisions/durable-task-progress-belongs-in-the-thread-log.md`). The
ring stays, because the per-task channel stays and reports progress at the
worker's rate rather than the log's coalesced rate, and because its reader
serves the experiment, sweep and seed routes too, which carry no thread
events. The conversation and its durable tasks read the core ring only.

**No React, in any ring.** The hook layer, the chat-helpers context and the
per-task view-model folds stay in the host application.

**The rings are published from `dist`, and every consumer reads them.**
`tsc -p tsconfig.build.json` emits JavaScript and declarations for the three
entries into `dist/`; `exports` names `types` and `import` per ring against
those files, `files` ships `dist` alone, and `prepack` rebuilds so a pack is
never stale. A host installs the package from this repository at one
tag and compiles that packed `dist`, so `exports` governs what a host sees:
a ring that `exports` does not name is unreachable from a host, not merely
unpublished. The build keeps the core ring's claim literal: `importHelpers` is
off, so the emitted core imports nothing but its own relative modules, and a
consumer that installs the tarball alone gets exactly one package in
`node_modules`.

# Why

The reuse unit is a headless client that a React 18 monorepo site can adopt. A package whose only entry point imports the AI SDK
would make that site take the SDK to parse a frame, and would make the
conformance suite a test of the SDK's schema rather than of the protocol. The
split keeps the falsifiable part - the frames, the cursors, the reduction -
answerable without any framework in the room.

# What was rejected

**One module that imports the AI SDK throughout.** Rejected: it makes the
dependency-free claim untestable and taxes every non-SDK host.

**Reducing with the SDK's `readUIMessageStream` instead of writing the
reduction.** Rejected: the document specifies the reduction in section 9, so
delegating it would leave section 9 unverified and would put the rule in a
library the document says a reader does not need.

**Vendoring nothing and reading `PROTOCOL.md` at test time.** Rejected: the
document is a sibling package in this repository and would not be one for a
published consumer. The capture is generated into the package by
`yarn sync:protocol` and a suite test regenerates it and compares, so a
document change fails the gate rather than passing silently.

**Porting the per-task view-model folds.** Rejected: they fold a host's own
progress payloads for rendering, name no frame, and would have arrived in the
package as callbacks with one caller.

**A condition or `publishConfig` that points `exports` at `src` in the
repository and at `dist` when published.** Rejected: it gives one import two
meanings, so this repository and a host would exercise different files under the same
specifier, and the conformance suite would then prove nothing about the
artifact a host installs. One honest `exports` map suffices.
