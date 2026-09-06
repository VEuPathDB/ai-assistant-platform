# @pathfinder/assistant-client

A headless TypeScript client for the assistant runtime wire protocol. It is
built from `PROTOCOL.md`, not from the app that uses it,
and its test suite is the protocol's consumer-side conformance suite.

## Entry points

| Import                                | Dependencies         | Holds                                                                       |
| ------------------------------------- | -------------------- | --------------------------------------------------------------------------- |
| `@pathfinder/assistant-client`        | none                 | Frame reader, cursors, reduction, snapshot, request body, `AssistantClient` |
| `@pathfinder/assistant-client/ai-sdk` | `ai` (optional peer) | `DurableChatTransport` and `resumeDurableThread` for `useChat`              |
| `@pathfinder/assistant-client/legacy` | none                 | **Deprecated.** The per-task progress dialect                               |

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
import { AssistantClient, webStorageCursorStore } from "@pathfinder/assistant-client";

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
