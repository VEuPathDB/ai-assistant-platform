import { describe, expect, it } from "vitest";

import { AssistantClient, AssistantHttpError } from "../../src/core/client.ts";
import { memoryCursorStore } from "../../src/core/cursor.ts";
import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { DONE_PAYLOAD, KEEPALIVE_FRAME, frameText } from "../../src/core/sse.ts";

interface Call {
  url: string;
  headers: Record<string, string>;
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

function stubFetch(responses: Response[]): {
  fetch: typeof globalThis.fetch;
  calls: Call[];
} {
  const calls: Call[] = [];
  const queue = [...responses];
  const fetchStub: typeof globalThis.fetch = (input, init) => {
    const url = urlOf(input);
    const headers = new Headers(init?.headers);
    calls.push({ url, headers: Object.fromEntries(headers.entries()) });
    const next = queue.shift();
    if (next === undefined) throw new Error(`no stub response for ${url}`);
    return Promise.resolve(next);
  };
  return { fetch: fetchStub, calls };
}

function sseResponse(body: string, status = 200): Response {
  return new Response(status === 204 ? null : body, {
    status,
    headers: { "content-type": "text/event-stream" },
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function clientWith(
  responses: Response[],
  extra: { cursors?: ReturnType<typeof memoryCursorStore> } = {},
): { client: AssistantClient; calls: Call[] } {
  const { fetch, calls } = stubFetch(responses);
  const client = new AssistantClient({
    fetch,
    eventsUrlFor: (id) => `/conversations/${id}/events`,
    snapshotUrlFor: (id) => `/conversations/${id}/events/snapshot`,
    ...(extra.cursors === undefined ? {} : { cursors: extra.cursors }),
  });
  return { client, calls };
}

async function drain(chunks: AsyncIterable<ProtocolChunk>): Promise<ProtocolChunk[]> {
  const seen: ProtocolChunk[] = [];
  for await (const chunk of chunks) seen.push(chunk);
  return seen;
}

const TURN =
  frameText(10, '{"type":"start","messageId":"a1"}') +
  KEEPALIVE_FRAME +
  frameText(11, '{"type":"text-start","id":"t"}') +
  frameText(12, '{"type":"text-delta","id":"t","delta":"hi"}') +
  frameText(13, '{"type":"finish","finishReason":"stop"}') +
  frameText(14, DONE_PAYLOAD);

describe("section 2, the tail", () => {
  it("reads every chunk of a turn and stops at the terminator", async () => {
    const { client } = clientWith([sseResponse(TURN)]);

    const tail = await client.openTail("c1");
    if (tail.status !== "streaming") throw new Error("expected a live turn");

    expect((await drain(tail.chunks)).map((chunk) => chunk.type)).toEqual([
      "start",
      "text-start",
      "text-delta",
      "finish",
    ]);
  });

  it("passes keep-alive comments through without a chunk", async () => {
    const { client } = clientWith([sseResponse(KEEPALIVE_FRAME + KEEPALIVE_FRAME)]);

    const tail = await client.openTail("c1");
    if (tail.status !== "streaming") throw new Error("expected a live turn");

    expect(await drain(tail.chunks)).toEqual([]);
  });

  it("asks from cursor zero when it holds nothing", async () => {
    const { client, calls } = clientWith([sseResponse(TURN)]);

    await client.openTail("c1");

    expect(calls[0]?.url).toBe("/conversations/c1/events?after=0");
  });

  it("asks from the cursor it persisted", async () => {
    const cursors = memoryCursorStore();
    cursors.write("c1", 14);
    const { client, calls } = clientWith([sseResponse("")], { cursors });

    await client.openTail("c1");

    expect(calls[0]?.url).toBe("/conversations/c1/events?after=14");
  });

  it("persists the terminator's cursor so the next read resumes after it", async () => {
    const cursors = memoryCursorStore();
    const { client } = clientWith([sseResponse(TURN)], { cursors });

    const tail = await client.openTail("c1");
    if (tail.status !== "streaming") throw new Error("expected a live turn");
    await drain(tail.chunks);

    expect(cursors.read("c1")).toBe(14);
  });

  it("resumes byte-identically: a split read yields what one read yields", async () => {
    const cursors = memoryCursorStore();
    const whole = clientWith([sseResponse(TURN)]);
    const wholeTail = await whole.client.openTail("c1");
    if (wholeTail.status !== "streaming") throw new Error("expected a live turn");
    const inOneRead = await drain(wholeTail.chunks);

    const firstHalf =
      frameText(10, '{"type":"start","messageId":"a1"}') +
      frameText(11, '{"type":"text-start","id":"t"}') +
      frameText(12, '{"type":"text-delta","id":"t","delta":"hi"}') +
      frameText(13, DONE_PAYLOAD);
    const split = clientWith(
      [
        sseResponse(firstHalf),
        sseResponse(
          frameText(14, '{"type":"finish","finishReason":"stop"}') +
            frameText(15, DONE_PAYLOAD),
        ),
      ],
      { cursors },
    );

    const first = await split.client.openTail("c1");
    if (first.status !== "streaming") throw new Error("expected a live turn");
    const before = await drain(first.chunks);
    const second = await split.client.openTail("c1");
    if (second.status !== "streaming") throw new Error("expected a live turn");
    const after = await drain(second.chunks);

    expect([...before, ...after]).toEqual(inOneRead);
    expect(split.calls[1]?.url).toBe("/conversations/c1/events?after=13");
  });

  it("reports an idle thread so the caller takes a snapshot", async () => {
    const { client } = clientWith([sseResponse("", 204)]);

    expect(await client.openTail("c1")).toEqual({ status: "idle" });
  });

  it("refuses a frame shape the protocol does not define", async () => {
    const { client } = clientWith([sseResponse("event: stream\ndata: {}\n\n")]);

    const tail = await client.openTail("c1");
    if (tail.status !== "streaming") throw new Error("expected a live turn");

    await expect(drain(tail.chunks)).rejects.toThrow(/frame is not id\/data\/comment/);
  });

  it("reports the status when the host refuses the read", async () => {
    const { client } = clientWith([jsonResponse({ detail: "gone" }, 404)]);

    await expect(client.openTail("c1")).rejects.toThrow(AssistantHttpError);
  });
});

describe("section 2, the snapshot", () => {
  it("rebuilds the conversation and reports the cursor it read to", async () => {
    const { client } = clientWith([
      jsonResponse({
        cursor: 14,
        chunks: [
          { type: "user-message", message: { id: "u1", role: "user", parts: [] } },
          { type: "start", messageId: "a1" },
          { type: "text-start", id: "t" },
          { type: "text-delta", id: "t", delta: "hi" },
          { type: "text-end", id: "t" },
          { type: "finish", finishReason: "stop" },
          { type: "done" },
        ],
      }),
    ]);

    const snapshot = await client.snapshot("c1");

    expect(snapshot.cursor).toBe(14);
    expect(snapshot.messages.map((message) => message.id)).toEqual(["u1", "a1"]);
  });

  it("persists the snapshot's cursor so a tail continues from it", async () => {
    const cursors = memoryCursorStore();
    const { client } = clientWith([jsonResponse({ cursor: 21, chunks: [] })], {
      cursors,
    });

    await client.snapshot("c1");

    expect(cursors.read("c1")).toBe(21);
  });

  it("reads a thread with no history as an empty conversation", async () => {
    const { client } = clientWith([jsonResponse({ cursor: 0, chunks: [] })]);

    expect((await client.snapshot("c1")).messages).toEqual([]);
  });

  it("refuses a body that is not a snapshot", async () => {
    const { client } = clientWith([jsonResponse({ nope: true })]);

    await expect(client.snapshot("c1")).rejects.toThrow(/not a snapshot/);
  });

  it("reports the status when the host refuses the read", async () => {
    const { client } = clientWith([jsonResponse({ detail: "gone" }, 404)]);

    await expect(client.snapshot("c1")).rejects.toThrow(AssistantHttpError);
  });
});

describe("section 4, polling instead of holding a connection", () => {
  it("gives the same messages the tail would have built", async () => {
    const live = clientWith([sseResponse(TURN)]);
    const tail = await live.client.openTail("c1");
    if (tail.status !== "streaming") throw new Error("expected a live turn");
    const streamed = await drain(tail.chunks);

    const polled = clientWith([jsonResponse({ cursor: 14, chunks: streamed })]);

    expect((await polled.client.poll("c1")).map((message) => message.id)).toEqual([
      "a1",
    ]);
  });
});

describe("the client's request shape", () => {
  it("asks for an event stream and sends the host's headers", async () => {
    const { fetch, calls } = stubFetch([sseResponse(TURN)]);
    const client = new AssistantClient({
      fetch,
      eventsUrlFor: (id) => `/conversations/${id}/events`,
      snapshotUrlFor: (id) => `/conversations/${id}/events/snapshot`,
      headers: () => ({ authorization: "Bearer t" }),
    });

    await client.openTail("c1");

    expect(calls[0]?.headers["accept"]).toBe("text/event-stream");
    expect(calls[0]?.headers["authorization"]).toBe("Bearer t");
  });

  it("awaits headers a host resolves asynchronously", async () => {
    const { fetch, calls } = stubFetch([jsonResponse({ cursor: 0, chunks: [] })]);
    const client = new AssistantClient({
      fetch,
      eventsUrlFor: (id) => `/conversations/${id}/events`,
      snapshotUrlFor: (id) => `/conversations/${id}/events/snapshot`,
      headers: () => Promise.resolve({ authorization: "Bearer later" }),
    });

    await client.snapshot("c1");

    expect(calls[0]?.headers["authorization"]).toBe("Bearer later");
  });
});
