import { describe, expect, it } from "vitest";

import { readTypedEvents } from "../../src/legacy/typedEventFrames.ts";
import { MalformedFrameError, parseFrame } from "../../src/core/sse.ts";

function streamOf(...pieces: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
}

async function read<T>(...pieces: string[]): Promise<T[]> {
  const events: T[] = [];
  for await (const event of readTypedEvents<T>(streamOf(...pieces))) events.push(event);
  return events;
}

describe("the task dialect is not the wire protocol", () => {
  it("frames with `event:`, which the protocol's reader refuses", () => {
    expect(() => parseFrame('event: stream\ndata: {"v":1}\n\n')).toThrow(
      MalformedFrameError,
    );
  });
});

describe("readTypedEvents", () => {
  it("parses frames into typed events", async () => {
    expect(
      await read('event: stream\ndata: {"x":1}\n\nevent: stream\ndata: {"x":2}\n\n'),
    ).toEqual([{ x: 1 }, { x: 2 }]);
  });

  it("ends on the done payload even when more data follows", async () => {
    expect(
      await read(
        'event: stream\ndata: {"v":1}\n\ndata: [DONE]\n\nevent: stream\ndata: {"v":2}\n\n',
      ),
    ).toEqual([{ v: 1 }]);
  });

  it("joins a frame split across two reads", async () => {
    expect(await read('event: stream\ndata: {"a', '":"hello"}\n\n')).toEqual([
      { a: "hello" },
    ]);
  });

  it("skips a payload that is not JSON", async () => {
    expect(
      await read(
        'event: stream\ndata: not-json\n\nevent: stream\ndata: {"ok":true}\n\n',
      ),
    ).toEqual([{ ok: true }]);
  });

  it("skips a comment frame that carries no data line", async () => {
    expect(await read(': keepalive\n\nevent: stream\ndata: {"v":1}\n\n')).toEqual([
      { v: 1 },
    ]);
  });

  it("reads several frames from one read", async () => {
    expect(
      await read(
        'event: stream\ndata: {"v":1}\n\nevent: stream\ndata: {"v":2}\n\nevent: stream\ndata: {"v":3}\n\n',
      ),
    ).toEqual([{ v: 1 }, { v: 2 }, { v: 3 }]);
  });

  it("ends when the body ends without a done payload", async () => {
    expect(await read('event: stream\ndata: {"v":1}\n\n')).toEqual([{ v: 1 }]);
  });

  it("drops bytes with no frame terminator", async () => {
    expect(await read('event: stream\ndata: {"v":1}')).toEqual([]);
  });

  it("reads the last data line when a frame carries several", async () => {
    expect(await read('data: {"first":true}\ndata: {"second":true}\n\n')).toEqual([
      { second: true },
    ]);
  });
});
