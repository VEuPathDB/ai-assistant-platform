import { type UIMessage, type UIMessageChunk } from "ai";
import { describe, expect, it } from "vitest";

import { DurableChatTransport } from "../../src/ai-sdk/DurableChatTransport.ts";
import { type CursorStore, memoryCursorStore } from "../../src/core/cursor.ts";
import { DONE_PAYLOAD, frameText } from "../../src/core/sse.ts";

const OPEN = "22222222-2222-2222-2222-222222222222";
const NEXT = "44444444-4444-4444-4444-444444444444";
const TASK = "00000000-0000-0000-0000-0000000000bb";

function frame(eventId: number, payload: unknown): string {
  return frameText(eventId, JSON.stringify(payload));
}

function done(eventId: number): string {
  return frameText(eventId, DONE_PAYLOAD);
}

const START = { type: "start", messageId: OPEN };
const TASK_STARTED = {
  type: "data-background-task-started",
  data: { taskId: TASK, toolName: "run_control_tests_on_step" },
};
const SUSPENDS = { type: "finish", finishReason: "other" };
const PROGRESS = {
  type: "data-task-progress",
  id: TASK,
  data: { taskId: TASK, percent: 0.6, message: "Comparing controls" },
};

/** The tail of a turn that parked a durable task, and the gap after it. */
const SUSPENDED_TAIL =
  frame(31, START) + frame(32, TASK_STARTED) + frame(39, SUSPENDS) + done(40);
const GAP = frame(41, PROGRESS) + done(42);

function eventStream(body: BodyInit): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "x-vercel-ai-ui-message-stream": "v1",
    },
  });
}

/** A store seeded the way a turn that parked a task leaves it. */
function suspendedCursors(): CursorStore {
  const store = memoryCursorStore();
  store.write("c1", 40);
  store.writeOpenMessage("c1", { messageId: OPEN, after: 30 });
  return store;
}

interface Host {
  transport: DurableChatTransport<UIMessage>;
  asked: string[];
}

/** A transport on one thread whose tails the test answers by their cursor. */
function host(
  serve: (after: string, init: RequestInit | undefined) => Promise<Response>,
  cursors: CursorStore = suspendedCursors(),
): Host {
  const asked: string[] = [];
  const transport = new DurableChatTransport<UIMessage>({
    api: "/api/v1/chat",
    conversationId: "c1",
    eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
    cursors,
    fetch: (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      const after = new URL(url, "http://host").searchParams.get("after") ?? "";
      asked.push(after);
      if (init?.signal?.aborted === true) {
        return Promise.reject(
          new DOMException("The operation was aborted.", "AbortError"),
        );
      }
      return serve(after, init);
    },
  });
  return { transport, asked };
}

/** A host that answers each cursor from a fixed body, and 204 for the rest. */
function servedBy(bodies: Record<string, string>) {
  return (after: string): Promise<Response> => {
    const body = bodies[after];
    return Promise.resolve(
      body === undefined ? new Response(null, { status: 204 }) : eventStream(body),
    );
  };
}

async function chunksOf(
  stream: ReadableStream<UIMessageChunk> | null,
): Promise<UIMessageChunk[]> {
  if (stream === null) return [];
  const chunks: UIMessageChunk[] = [];
  const reader = stream.getReader();
  for (;;) {
    const next = await reader.read();
    if (next.done === true) break;
    chunks.push(next.value);
  }
  return chunks;
}

interface Deferred<T> {
  promise: Promise<T>;
  settle: (value: T) => void;
  fail: (reason: Error) => void;
}

function deferred<T>(): Deferred<T> {
  let settle: (value: T) => void = () => undefined;
  let fail: (reason: Error) => void = () => undefined;
  const promise = new Promise<T>((resolve, reject) => {
    settle = resolve;
    fail = reject;
  });
  return { promise, settle, fail };
}

/** A body the test writes frame by frame, to time an abort inside one tail. */
function writtenBody(): {
  body: ReadableStream<Uint8Array>;
  write: (text: string) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let sink: ReadableStreamDefaultController<Uint8Array> | undefined;
  const body = new ReadableStream<Uint8Array>({
    start: (controller) => {
      sink = controller;
    },
  });
  return {
    body,
    write: (text) => sink?.enqueue(encoder.encode(text)),
    close: () => sink?.close(),
  };
}

/** A body a fired signal errors, the way an aborted fetch leaves its own. */
function abortableBody(
  text: string,
  signal: AbortSignal | null | undefined,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start: (controller) => {
      controller.enqueue(encoder.encode(text));
      signal?.addEventListener("abort", () => {
        controller.error(new DOMException("The operation was aborted.", "AbortError"));
      });
    },
  });
}

/** Let every microtask this stream queued run before the test looks again. */
async function settled(): Promise<void> {
  for (let turn = 0; turn < 20; turn += 1) await Promise.resolve();
}

describe("a reconnect that replays a message the client already holds", () => {
  it("delivers the whole message once, and the gap after it", async () => {
    const probe = host(servedBy({ "30": SUSPENDED_TAIL, "40": GAP }));

    const chunks = await chunksOf(
      await probe.transport.reconnectToStream({ chatId: "c1" }),
    );

    expect(probe.asked).toEqual(["30", "40", "42"]);
    expect(chunks).toEqual([START, TASK_STARTED, SUSPENDS, PROGRESS]);
  });
});

describe("two reconnects on one transport", () => {
  it("leaves the surviving one its tail chain", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const answers = [first, second];
    const probe = host((after) => {
      const pending = answers.shift();
      if (pending === undefined) return servedBy({ "40": GAP })(after);
      return pending.promise;
    });
    const superseded = new AbortController();
    const surviving = new AbortController();

    const abandoned = probe.transport.reconnectToStream({
      chatId: "c1",
      abortSignal: superseded.signal,
    });
    const kept = probe.transport.reconnectToStream({
      chatId: "c1",
      abortSignal: surviving.signal,
    });
    const abandonedEnds = expect(abandoned).rejects.toThrow(/aborted/);
    await settled();
    superseded.abort();
    first.fail(new DOMException("The operation was aborted.", "AbortError"));
    await abandonedEnds;
    second.settle(eventStream(SUSPENDED_TAIL));

    const chunks = await chunksOf(await kept);

    expect(probe.asked).toEqual(["30", "30", "40", "42"]);
    expect(chunks).toEqual([START, TASK_STARTED, SUSPENDS, PROGRESS]);
  });

  it("hands the next turn on from the surviving read alone", async () => {
    const gap = writtenBody();
    const probe = host((after) =>
      Promise.resolve(
        after === "30" ? eventStream(SUSPENDED_TAIL) : eventStream(gap.body),
      ),
    );
    const abandoned = new AbortController();

    const read = probe.transport.reconnectToStream({
      chatId: "c1",
      abortSignal: abandoned.signal,
    });
    await read;
    await settled();
    abandoned.abort();
    gap.write(frame(41, { type: "start", messageId: NEXT }));
    gap.close();
    await settled();

    expect(probe.transport.takeHeldTurn()).toBeUndefined();
  });

  it("opens a fresh tail where the turn it holds came from a read that ended", async () => {
    const opens = frame(41, { type: "start", messageId: NEXT });
    const closes = frame(42, { type: "finish", finishReason: "stop" }) + done(43);
    let gaps = 0;
    const probe = host((after, init) => {
      if (after === "30") return Promise.resolve(eventStream(SUSPENDED_TAIL));
      gaps += 1;
      return Promise.resolve(
        eventStream(gaps === 1 ? abortableBody(opens, init?.signal) : opens + closes),
      );
    });
    const held = new AbortController();
    const adopting = new AbortController();

    await chunksOf(
      await probe.transport.reconnectToStream({
        chatId: "c1",
        abortSignal: held.signal,
      }),
    );
    await settled();
    held.abort();
    const chunks = await chunksOf(
      await probe.transport.reconnectToStream({
        chatId: "c1",
        abortSignal: adopting.signal,
      }),
    );

    expect(probe.asked).toEqual(["30", "40", "40"]);
    expect(chunks).toEqual([
      { type: "start", messageId: NEXT },
      { type: "finish", finishReason: "stop" },
    ]);
  });
});

describe("a tail chain under a signal that fires", () => {
  it("ends where the signal fired, and asks for no further tail", async () => {
    const tail = writtenBody();
    const probe = host(() => Promise.resolve(eventStream(tail.body)));
    const stopped = new AbortController();

    const stream = await probe.transport.reconnectToStream({
      chatId: "c1",
      abortSignal: stopped.signal,
    });
    tail.write(frame(31, START) + frame(32, TASK_STARTED) + frame(39, SUSPENDS));
    await settled();
    stopped.abort();
    tail.write(done(40));
    tail.close();

    expect(await chunksOf(stream)).toEqual([START, TASK_STARTED, SUSPENDS]);
    expect(probe.asked).toEqual(["30"]);
  });
});
