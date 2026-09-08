import { type UIMessage } from "ai";
import { describe, expect, it } from "vitest";

import {
  DurableChatTransport,
  type Replay,
} from "../../src/ai-sdk/DurableChatTransport.ts";
import { AssistantClient } from "../../src/core/client.ts";
import { memoryCursorStore, webStorageCursorStore } from "../../src/core/cursor.ts";
import { readFrames } from "../../src/core/sse.ts";
import {
  COMPLETED_TURN,
  EARLIER,
  FIRST_CURSOR,
  GAP_AND_CONTINUATION,
  RESUMED,
  SUSPENDED,
  SUSPENDED_DONE,
  SUSPENDED_PARTS,
  SUSPENDED_START,
  SUSPENDED_THREAD,
  SUSPENDING_TAIL,
  SUSPENDING_TURN,
  TASK,
  bodyOf,
  harness,
  heldSuspendedMessage,
  logOf,
  seedSuspended,
} from "./durableResume.ts";

const EARLIER_DONE = FIRST_CURSOR + COMPLETED_TURN.length - 1;
const LATE_SUSPENDED_DONE = EARLIER_DONE + SUSPENDING_TURN.length;

function memoryStorage(): () => Storage {
  const entries = new Map<string, string>();
  return () =>
    ({
      getItem: (key: string) => entries.get(key) ?? null,
      setItem: (key: string, value: string) => {
        entries.set(key, value);
      },
      removeItem: (key: string) => {
        entries.delete(key);
      },
    }) as Storage;
}

class PayloadProbe extends DurableChatTransport<UIMessage> {
  payloads(body: string, replay: Replay): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    const bytes = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    });
    return this.acceptedPayloads(
      readFrames(bytes, { allowTruncatedTail: true }),
      replay,
    );
  }
}

/** Every byte chunk the transport wrote, as the SDK's reader receives them. */
async function payloadsOf(body: string): Promise<string[]> {
  const probe = new PayloadProbe({
    api: "/api/v1/chat",
    conversationId: "c1",
    eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
    cursors: seedSuspended(memoryCursorStore(), {
      after: SUSPENDED_START,
      done: SUSPENDED_DONE,
    }),
  });
  const reader = probe
    .payloads(body, {
      resuming: true,
      messageId: SUSPENDED,
      through: SUSPENDED_DONE,
    })
    .getReader();
  const decoder = new TextDecoder();
  const written: string[] = [];
  for (;;) {
    const next = await reader.read();
    if (next.done === true) return written;
    written.push(decoder.decode(next.value));
  }
}

describe("a resume of a message the client already holds", () => {
  it("replays that message from its start, so no part of it is lost", async () => {
    const probe = harness({
      thread: SUSPENDED_THREAD,
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
    });

    await probe.resume();

    expect(probe.urls[0]).toBe(
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
    );
    expect(probe.chat.messages[0]?.parts).toEqual([
      {
        type: "data-background-task-started",
        data: { taskId: TASK, toolName: "optimize_search_parameters" },
      },
      { type: "data-task-progress", id: TASK, data: { taskId: TASK, percent: 0.9 } },
      { type: "data-task-completed", data: { taskId: TASK, status: "success" } },
    ]);
  });

  it("hands the prefix it replays to the SDK as one write", async () => {
    const replayed = await payloadsOf(bodyOf(SUSPENDING_TAIL));

    expect(replayed).toEqual([
      [
        `data: ${JSON.stringify(SUSPENDING_TURN[0])}\n\n`,
        `data: ${JSON.stringify(SUSPENDING_TURN[1])}\n\n`,
        `data: ${JSON.stringify(SUSPENDING_TURN[2])}\n\n`,
      ].join(""),
    ]);
  });

  it("streams what the tail adds after that prefix one chunk at a time", async () => {
    const replayed = await payloadsOf(bodyOf(SUSPENDED_THREAD));

    expect(replayed.slice(1)).toEqual([
      `data: ${JSON.stringify(GAP_AND_CONTINUATION[0])}\n\n`,
      `data: ${JSON.stringify(GAP_AND_CONTINUATION[1])}\n\n`,
    ]);
  });

  it("tails from the open message the snapshot handed the store", async () => {
    const cursors = memoryCursorStore();
    const client = new AssistantClient({
      cursors,
      eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
      snapshotUrlFor: (id) => `/api/v1/conversations/${id}/events/snapshot`,
      fetch: () =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              cursor: SUSPENDED_DONE,
              chunks: SUSPENDING_TURN,
              openMessage: { messageId: SUSPENDED, after: SUSPENDED_START },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        ),
    });
    const restored = await client.snapshot("c1");

    const probe = harness({ thread: SUSPENDED_THREAD, cursors });
    probe.chat.messages = restored.messages;
    await probe.resume();

    expect(probe.urls[0]).toBe(
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
    );
    expect(probe.shape()).toEqual([
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("tails from the cursor a reload read out of storage", async () => {
    const cursors = seedSuspended(webStorageCursorStore({ storage: memoryStorage() }), {
      after: SUSPENDED_START,
      done: SUSPENDED_DONE,
    });

    const probe = harness({
      thread: SUSPENDED_THREAD,
      cursors,
      holds: [heldSuspendedMessage()],
    });
    await probe.resume();

    expect(probe.urls[0]).toBe(
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
    );
    expect(probe.shape()).toEqual([
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("drops what the tail delivers before that message's start", async () => {
    const earlier: UIMessage = {
      id: EARLIER,
      role: "assistant",
      parts: [{ type: "text", text: "Ninety-one genes.", state: "done" }],
    };
    const probe = harness({
      thread: logOf([...COMPLETED_TURN, ...SUSPENDING_TURN, ...GAP_AND_CONTINUATION]),
      cursors: seedSuspended(memoryCursorStore(), {
        after: 0,
        done: LATE_SUSPENDED_DONE,
      }),
      holds: [earlier, heldSuspendedMessage()],
    });

    await probe.resume();

    expect(probe.urls).toEqual([
      "/api/v1/conversations/c1/events?after=0",
      `/api/v1/conversations/c1/events?after=${String(EARLIER_DONE)}`,
      `/api/v1/conversations/c1/events?after=${String(LATE_SUSPENDED_DONE)}`,
    ]);
    expect(probe.shape()).toEqual([
      { id: EARLIER, role: "assistant", parts: ["text"] },
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("does not replay a message whose turn ran to completion", async () => {
    const thread = logOf(COMPLETED_TURN);
    const probe = harness({ thread, post: thread });

    await probe.chat.sendMessage({ text: "how many genes" });
    await probe.resume();

    expect(probe.urls).toEqual([
      "/api/v1/chat",
      `/api/v1/conversations/c1/events?after=${String(EARLIER_DONE)}`,
    ]);
    expect(probe.shape()).toEqual([
      { id: probe.chat.messages[0]?.id ?? "", role: "user", parts: ["text"] },
      { id: EARLIER, role: "assistant", parts: ["text"] },
    ]);
  });
});
