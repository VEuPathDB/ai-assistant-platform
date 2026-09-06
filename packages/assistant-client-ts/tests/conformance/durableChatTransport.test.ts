import { type UIMessage, type UIMessageChunk } from "ai";
import { describe, expect, it } from "vitest";

import { DurableChatTransport } from "../../src/ai-sdk/DurableChatTransport.ts";
import { type CursorStore, memoryCursorStore } from "../../src/core/cursor.ts";
import { DONE_PAYLOAD, KEEPALIVE_FRAME, frameText } from "../../src/core/sse.ts";

class ProbeTransport extends DurableChatTransport<UIMessage> {
  parse(body: string): ReadableStream<UIMessageChunk> {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    });
    return this.processResponseStream(stream);
  }

  async reconnectUrl(): Promise<string> {
    const prepare = this.prepareReconnectToStreamRequest;
    if (prepare === undefined) throw new Error("no reconnect preparation");
    const request = await prepare({
      id: "c1",
      api: "/api/v1/chat",
      requestMetadata: undefined,
      body: undefined,
      credentials: undefined,
      headers: undefined,
    });
    if (request.api === undefined) throw new Error("no reconnect url");
    return request.api;
  }
}

function probe(
  options: { cursors?: CursorStore; onUnhandledChunk?: (chunk: unknown) => void } = {},
) {
  return new ProbeTransport({
    api: "/api/v1/chat",
    conversationId: "c1",
    eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
    cursors: options.cursors ?? memoryCursorStore(),
    ...(options.onUnhandledChunk === undefined
      ? {}
      : { onUnhandledChunk: options.onUnhandledChunk }),
  });
}

async function chunksOf(
  body: string,
  options: { cursors?: CursorStore; onUnhandledChunk?: (chunk: unknown) => void } = {},
): Promise<UIMessageChunk[]> {
  const reader = probe(options).parse(body).getReader();
  const chunks: UIMessageChunk[] = [];
  let next = await reader.read();
  while (next.done !== true) {
    chunks.push(next.value);
    next = await reader.read();
  }
  return chunks;
}

const QUEUED = '{"type":"data-turn-status","data":{"label":"Queued"}}';
const START = '{"type":"start","messageId":"m1"}';

describe("the transport reads the wire the protocol defines", () => {
  it("drops keep-alive comments and keeps every real chunk", async () => {
    const body =
      frameText(1, QUEUED) +
      KEEPALIVE_FRAME +
      KEEPALIVE_FRAME +
      frameText(2, START) +
      frameText(3, DONE_PAYLOAD);

    expect(await chunksOf(body)).toEqual([
      { type: "data-turn-status", data: { label: "Queued" } },
      { type: "start", messageId: "m1" },
    ]);
  });

  it("survives a stream that is nothing but keep-alives", async () => {
    expect(await chunksOf(KEEPALIVE_FRAME + KEEPALIVE_FRAME)).toEqual([]);
  });

  it("dies on a payload that is not JSON", async () => {
    await expect(
      chunksOf(frameText(1, START) + frameText(2, "keep-alive")),
    ).rejects.toThrow();
  });

  it("dies on a frame shape the protocol does not define", async () => {
    await expect(chunksOf("event: stream\ndata: {}\n\n")).rejects.toThrow(
      /frame is not id\/data\/comment/,
    );
  });

  it("drops the prompt envelopes the log keeps for snapshots", async () => {
    const body =
      frameText(
        1,
        '{"type":"user-message","message":{"id":"u1","role":"user","parts":[]}}',
      ) +
      frameText(
        2,
        '{"type":"system-message","message":{"id":"s1","role":"system","parts":[]}}',
      ) +
      frameText(
        3,
        '{"type":"assistant-message","message":{"id":"a0","role":"assistant","parts":[]}}',
      ) +
      frameText(4, START);

    expect(await chunksOf(body)).toEqual([{ type: "start", messageId: "m1" }]);
  });

  it("ignores a chunk kind a later runtime added, rather than killing the turn", async () => {
    const seen: unknown[] = [];
    const body =
      frameText(1, START) +
      frameText(2, '{"type":"invented-by-a-later-version","payload":1}') +
      frameText(3, '{"type":"finish","finishReason":"stop"}');

    const chunks = await chunksOf(body, {
      onUnhandledChunk: (chunk) => seen.push(chunk),
    });

    expect(chunks.map((chunk) => chunk.type)).toEqual(["start", "finish"]);
    expect(seen).toEqual([{ type: "invented-by-a-later-version", payload: 1 }]);
  });
});

describe("the transport resumes where it left off", () => {
  it("reconnects after the last turn boundary it saw", async () => {
    const cursors = memoryCursorStore();
    await chunksOf(frameText(9, START) + frameText(14, DONE_PAYLOAD), { cursors });

    expect(await probe({ cursors }).reconnectUrl()).toBe(
      "/api/v1/conversations/c1/events?after=14",
    );
  });

  it("reconnects from the whole thread when it has seen no turn end", async () => {
    const cursors = memoryCursorStore();
    await chunksOf(frameText(9, START), { cursors });

    expect(await probe({ cursors }).reconnectUrl()).toBe(
      "/api/v1/conversations/c1/events?after=0",
    );
  });
});
