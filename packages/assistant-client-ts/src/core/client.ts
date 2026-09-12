import { type ProtocolChunk, asRecord, parseChunk } from "./chunks.ts";
import {
  type CursorStore,
  type OpenMessage,
  memoryCursorStore,
  recordFrameCursor,
  tailUrl,
} from "./cursor.ts";
import { type ThreadMessage } from "./message.ts";
import { type Snapshot, reduceSnapshot, turnIsInFlight } from "./snapshot.ts";
import { isComment, isDone, readFrames } from "./sse.ts";

export class AssistantHttpError extends Error {
  readonly status: number;
  readonly url: string;

  constructor(url: string, status: number) {
    super(`assistant read failed: ${String(status)} ${url}`);
    this.name = "AssistantHttpError";
    this.status = status;
    this.url = url;
  }
}

export interface AssistantClientOptions {
  eventsUrlFor: (threadId: string) => string;
  snapshotUrlFor: (threadId: string) => string;
  fetch?: typeof globalThis.fetch;
  headers?: () => HeadersInit | Promise<HeadersInit>;
  cursors?: CursorStore;
}

export interface SnapshotResult {
  messages: ThreadMessage[];
  cursor: number;
  /** Section 4: a turn is running, and the reader follows it with a tail. */
  turnInFlight: boolean;
}

export type TailResult =
  { status: "streaming"; chunks: AsyncGenerator<ProtocolChunk> } | { status: "idle" };

export interface TailOptions {
  signal?: AbortSignal;
}

const NO_TURN_IN_FLIGHT = 204;

function readOpenMessage(value: unknown): OpenMessage | undefined {
  const record = asRecord(value);
  if (record === undefined) return undefined;
  const messageId = record["messageId"];
  const after = record["after"];
  if (typeof messageId !== "string" || typeof after !== "number") return undefined;
  return { messageId, after };
}

function readSnapshot(body: unknown): Snapshot {
  const record = asRecord(body);
  if (record === undefined) {
    throw new Error("assistant read failed: body is not a snapshot");
  }
  const chunks = record["chunks"];
  const cursor = record["cursor"];
  if (!Array.isArray(chunks) || typeof cursor !== "number") {
    throw new Error("assistant read failed: body is not a snapshot");
  }
  const openMessage = readOpenMessage(record["openMessage"]);
  return { chunks, cursor, ...(openMessage === undefined ? {} : { openMessage }) };
}

/** A client for one assistant runtime, built from the wire protocol alone. */
export class AssistantClient {
  private readonly options: AssistantClientOptions;
  private readonly cursors: CursorStore;

  constructor(options: AssistantClientOptions) {
    this.options = options;
    this.cursors = options.cursors ?? memoryCursorStore();
  }

  private async request(
    url: string,
    accept: string,
    signal?: AbortSignal,
  ): Promise<Response> {
    const headers = new Headers(await this.options.headers?.());
    headers.set("accept", accept);
    const fetchImpl = this.options.fetch ?? globalThis.fetch;
    const response = await fetchImpl(url, {
      headers,
      ...(signal === undefined ? {} : { signal }),
    });
    if (!response.ok && response.status !== NO_TURN_IN_FLIGHT) {
      throw new AssistantHttpError(url, response.status);
    }
    return response;
  }

  /** Read the completed history, plus the prompt of any turn in flight. */
  async snapshot(threadId: string): Promise<SnapshotResult> {
    const url = this.options.snapshotUrlFor(threadId);
    const response = await this.request(url, "application/json");
    const snapshot = readSnapshot(await response.json());
    if (snapshot.cursor > this.cursors.read(threadId)) {
      this.cursors.write(threadId, snapshot.cursor);
    }
    this.cursors.writeOpenMessage(threadId, snapshot.openMessage);
    return {
      messages: reduceSnapshot(snapshot.chunks),
      cursor: snapshot.cursor,
      turnInFlight: turnIsInFlight(snapshot.chunks),
    };
  }

  /** Read the snapshot as the whole conversation, for a host that cannot stream. */
  async poll(threadId: string): Promise<ThreadMessage[]> {
    return (await this.snapshot(threadId)).messages;
  }

  /** Follow the thread from the cursor this client holds. */
  async openTail(threadId: string, options: TailOptions = {}): Promise<TailResult> {
    const url = tailUrl(
      this.options.eventsUrlFor(threadId),
      this.cursors.read(threadId),
    );
    const response = await this.request(url, "text/event-stream", options.signal);
    if (response.status === NO_TURN_IN_FLIGHT || response.body === null) {
      return { status: "idle" };
    }
    return { status: "streaming", chunks: this.readChunks(threadId, response.body) };
  }

  private async *readChunks(
    threadId: string,
    body: ReadableStream<Uint8Array>,
  ): AsyncGenerator<ProtocolChunk> {
    for await (const frame of readFrames(body, { allowTruncatedTail: true })) {
      if (isComment(frame) || frame.data === undefined) continue;
      const chunk = isDone(frame) ? undefined : parseChunk(frame.data);
      recordFrameCursor(this.cursors, threadId, frame, chunk);
      if (chunk !== undefined) yield chunk;
    }
  }
}
