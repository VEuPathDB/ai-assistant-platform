export const DONE_PAYLOAD = "[DONE]";
export const KEEPALIVE_FRAME = ": keep-alive\n\n";

const FRAME_TERMINATOR = "\n\n";
const ID_FIELD = "id: ";
const DATA_FIELD = "data: ";

/** A frame the wire protocol does not define. */
export class MalformedFrameError extends Error {
  readonly raw: string;

  constructor(raw: string) {
    super(`frame is not id/data/comment: ${JSON.stringify(raw)}`);
    this.name = "MalformedFrameError";
    this.raw = raw;
  }
}

/** One SSE frame: its cursor, its payload, and the bytes it arrived as. */
export interface Frame {
  readonly raw: string;
  readonly eventId?: number;
  readonly data?: string;
}

export function isComment(frame: Frame): boolean {
  return frame.eventId === undefined && frame.data === undefined;
}

export function isDone(frame: Frame): boolean {
  return frame.data === DONE_PAYLOAD;
}

export function frameText(eventId: number, data: string): string {
  return `id: ${String(eventId)}\ndata: ${data}${FRAME_TERMINATOR}`;
}

function isDecimal(value: string): boolean {
  return value.length > 0 && /^[0-9]+$/.test(value);
}

/** Read one frame. Throws when it is neither an event nor a comment. */
export function parseFrame(raw: string): Frame {
  if (!raw.endsWith(FRAME_TERMINATOR)) throw new MalformedFrameError(raw);
  const lines = raw.slice(0, -FRAME_TERMINATOR.length).split("\n");
  if (lines.every((line) => line.startsWith(":"))) return { raw };
  let eventId: number | undefined;
  let data: string | undefined;
  for (const line of lines) {
    if (line.startsWith(ID_FIELD)) {
      const cursor = line.slice(ID_FIELD.length);
      if (!isDecimal(cursor)) throw new MalformedFrameError(raw);
      eventId = Number.parseInt(cursor, 10);
    } else if (line.startsWith(DATA_FIELD)) {
      data = line.slice(DATA_FIELD.length);
    } else {
      throw new MalformedFrameError(raw);
    }
  }
  if (eventId === undefined || data === undefined) throw new MalformedFrameError(raw);
  return { raw, eventId, data };
}

export interface ReadFramesOptions {
  /**
   * Treat bytes with no terminator at end of stream as a closed connection
   * rather than as a protocol break.
   */
  allowTruncatedTail?: boolean;
}

/** Split a byte stream into frames and parse each one strictly. */
export async function* readFrames(
  stream: ReadableStream<Uint8Array>,
  options: ReadFramesOptions = {},
): AsyncGenerator<Frame> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done === true) break;
      buffer += decoder.decode(next.value, { stream: true });
      let boundary = buffer.indexOf(FRAME_TERMINATOR);
      while (boundary >= 0) {
        const raw = buffer.slice(0, boundary + FRAME_TERMINATOR.length);
        buffer = buffer.slice(boundary + FRAME_TERMINATOR.length);
        yield parseFrame(raw);
        boundary = buffer.indexOf(FRAME_TERMINATOR);
      }
    }
    buffer += decoder.decode();
    if (buffer.length > 0 && options.allowTruncatedTail !== true) {
      throw new MalformedFrameError(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}
