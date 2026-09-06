import { describe, expect, it } from "vitest";

import {
  DONE_PAYLOAD,
  KEEPALIVE_FRAME,
  MalformedFrameError,
  frameText,
  isComment,
  isDone,
  parseFrame,
  readFrames,
} from "../../src/core/sse.ts";

function textStream(...pieces: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
}

async function collect(...pieces: string[]): Promise<string[]> {
  const raw: string[] = [];
  for await (const frame of readFrames(textStream(...pieces))) raw.push(frame.raw);
  return raw;
}

describe("parseFrame, section 3", () => {
  it("reads an event frame's cursor and payload", () => {
    const frame = parseFrame('id: 7\ndata: {"type":"start"}\n\n');

    expect(frame.eventId).toBe(7);
    expect(frame.data).toBe('{"type":"start"}');
    expect(isComment(frame)).toBe(false);
  });

  it("reads a comment frame as carrying no cursor and no payload", () => {
    const frame = parseFrame(KEEPALIVE_FRAME);

    expect(isComment(frame)).toBe(true);
    expect(frame.eventId).toBeUndefined();
    expect(frame.data).toBeUndefined();
  });

  it("reads the terminator as data, not as a frame shape of its own", () => {
    const frame = parseFrame(`id: 9\ndata: ${DONE_PAYLOAD}\n\n`);

    expect(isDone(frame)).toBe(true);
    expect(frame.eventId).toBe(9);
  });

  it("refuses a frame that is not blank-line terminated", () => {
    expect(() => parseFrame('id: 1\ndata: {"type":"start"}\n')).toThrow(
      MalformedFrameError,
    );
  });

  it("refuses a field the protocol does not define", () => {
    expect(() => parseFrame('event: stream\ndata: {"type":"start"}\n\n')).toThrow(
      MalformedFrameError,
    );
  });

  it("refuses a cursor that is not a decimal integer", () => {
    expect(() => parseFrame('id: seven\ndata: {"type":"start"}\n\n')).toThrow(
      MalformedFrameError,
    );
  });

  it("refuses an event frame with no cursor", () => {
    expect(() => parseFrame('data: {"type":"start"}\n\n')).toThrow(MalformedFrameError);
  });

  it("refuses an event frame with no payload", () => {
    expect(() => parseFrame("id: 4\n\n")).toThrow(MalformedFrameError);
  });

  it("keeps the bytes it arrived as", () => {
    const raw = 'id: 3\ndata: {"type":"finish"}\n\n';

    expect(parseFrame(raw).raw).toBe(raw);
  });

  it("round-trips a frame it built", () => {
    const raw = frameText(12, '{"type":"text-end","id":"t"}');

    expect(parseFrame(raw).eventId).toBe(12);
    expect(parseFrame(raw).data).toBe('{"type":"text-end","id":"t"}');
  });
});

describe("readFrames, section 3", () => {
  it("splits a byte stream on the blank line", async () => {
    expect(await collect('id: 1\ndata: {"a":1}\n\nid: 2\ndata: {"a":2}\n\n')).toEqual([
      'id: 1\ndata: {"a":1}\n\n',
      'id: 2\ndata: {"a":2}\n\n',
    ]);
  });

  it("joins a frame split across two reads", async () => {
    expect(await collect('id: 1\ndata: {"a"', ":1}\n\n")).toEqual([
      'id: 1\ndata: {"a":1}\n\n',
    ]);
  });

  it("joins a frame split inside its terminator", async () => {
    expect(await collect('id: 1\ndata: {"a":1}\n', "\n")).toEqual([
      'id: 1\ndata: {"a":1}\n\n',
    ]);
  });

  it("passes comment frames through so the caller can ignore them", async () => {
    expect(await collect(KEEPALIVE_FRAME, 'id: 1\ndata: {"a":1}\n\n')).toEqual([
      KEEPALIVE_FRAME,
      'id: 1\ndata: {"a":1}\n\n',
    ]);
  });

  it("refuses a malformed frame mid-stream", async () => {
    await expect(
      collect('id: 1\ndata: {"a":1}\n\nevent: stream\ndata: x\n\n'),
    ).rejects.toThrow(MalformedFrameError);
  });

  it("ends cleanly when the stream closes on a frame boundary", async () => {
    expect(await collect('id: 1\ndata: {"a":1}\n\n')).toHaveLength(1);
  });

  it("refuses bytes left over when the stream closes mid-frame", async () => {
    await expect(collect('id: 1\ndata: {"a":1}\n\nid: 2\ndata: {"a"')).rejects.toThrow(
      MalformedFrameError,
    );
  });

  it("tolerates a truncated tail when the caller allows it", async () => {
    const raw: string[] = [];
    const stream = textStream('id: 1\ndata: {"a":1}\n\nid: 2\ndata: {"a"');
    for await (const frame of readFrames(stream, { allowTruncatedTail: true })) {
      raw.push(frame.raw);
    }

    expect(raw).toEqual(['id: 1\ndata: {"a":1}\n\n']);
  });
});
