# @veupathdb/assistant-client

A headless TypeScript client for the assistant runtime wire protocol. It is
built from `PROTOCOL.md`, not from the app that uses it,
and its test suite is the protocol's consumer-side conformance suite.

## Entry points

| Import                               | Dependencies         | Holds                                                                                         |
| ------------------------------------ | -------------------- | --------------------------------------------------------------------------------------------- |
| `@veupathdb/assistant-client`        | none                 | Frame reader, cursors, reduction, snapshot, request body, `AssistantClient`, the part readers |
| `@veupathdb/assistant-client/ai-sdk` | `ai` (optional peer) | `DurableChatTransport`, `resumeDurableThread` and `toTraceParts` for `useChat`                |
| `@veupathdb/assistant-client/legacy` | none                 | **Deprecated.** The per-task progress dialect                                                 |

No entry point imports React. A host supplies its own hooks, storage and
rendering.

`./legacy` is deprecated as of protocol 1.1.0. A durable task's whole
lifecycle - started, progress, completed - is on the thread, so the core ring
reads it with one reader and one cursor. Take `./legacy` only to follow a task
at the worker's own rate instead of the log's coalesced rate.

## Building and packing

`yarn build` runs `tsc -p tsconfig.build.json` and emits JavaScript and
declarations for the three entries into `dist/`. `exports` names those files,
`files` ships `dist` alone, and `prepack` rebuilds from scratch, so
`yarn pack` always packs the current source.

```bash
yarn build                        # dist/index.js, dist/ai-sdk.js, dist/legacy.js + .d.ts
yarn pack --out /tmp/client.tgz   # rebuilds first
```

The packed artifact is what a host installs. Inside this repository the app
resolves the package through its tsconfig `paths` and its vitest aliases, both
of which name `src`, so `dist` does not have to exist for the app to build or
to test.

## Reading a thread

```ts
import { AssistantClient, webStorageCursorStore } from "@veupathdb/assistant-client";

const client = new AssistantClient({
  eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
  snapshotUrlFor: (id) => `/api/v1/conversations/${id}/events/snapshot`,
  cursors: webStorageCursorStore(),
  headers: () => ({ authorization: `Bearer ${token}` }),
});

const { messages } = await client.snapshot(threadId);

const tail = await client.openTail(threadId);
if (tail.status === "idle") {
  // No turn in flight. Section 4 says take a snapshot.
} else {
  for await (const chunk of tail.chunks) render(chunk);
}
```

A host that cannot hold a connection calls `client.poll(threadId)` instead. The
ordering and the bytes are the same either way.

## Reading a message's parts

A host renders; the client folds. Each reader below takes the parts of a
message, or the messages of a thread, and answers one question:

```ts
import {
  buildTrace,
  orderedLanes,
  runningPhase,
  taskLifecycle,
  threadUsage,
  turnUsage,
} from "@veupathdb/assistant-client";

buildTrace(parts); // the runs of calls a turn made
runningPhase(parts); // the dispatch the turn still has open
turnUsage(parts); // the lead's own usage, and its dispatches
threadUsage(messages); // the same, summed over the thread
taskLifecycle(messages, taskId, { laneOf }); // one durable task, per lane
orderedLanes(lifecycle.lanes); // those lanes in a stable order
```

A count is read with the type the wire states: `tokens` is a number and
`costUsd` a decimal string, so a field of another type reads as nothing spent
and every reader of a chunk reports the same number. A task's lane names itself
inside `toolSpecific` under a key the producer chooses, so `laneOf` is the
host's; without it a task reads as one sequence.

### Behaviour these readers pin

Three readings differ from a fold written against one host's own shapes, and
each is deliberate:

- A count of a type the wire does not state reads as nothing spent.
- A dispatch that names no phase still counts toward the turn's total, and the
  trace groups it under its call id. An absent phase and an empty one read
  alike.
- A progress update that states neither a percent nor a message still opens a
  lane, with both fields null, rather than being dropped.

Under `useChat` the SDK holds its own part shapes. `toTraceParts` from the
`./ai-sdk` ring reads them as the shapes above.

## The conformance gate

`src/protocol/captured.json` is generated from `PROTOCOL.md` by
`yarn sync:protocol`. The suite regenerates it and compares, so the capture
cannot drift from the document. A second gate compares the document's chunk
table to the kinds the reducer answers to, so a kind the document adds fails
here until this client reads it.

```bash
yarn sync:protocol && yarn format   # after a PROTOCOL.md change
yarn test                           # conformance + unit
yarn typecheck
yarn lint
yarn format:check
yarn build
```
