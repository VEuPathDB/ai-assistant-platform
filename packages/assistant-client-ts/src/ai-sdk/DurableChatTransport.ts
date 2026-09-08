import {
  DefaultChatTransport,
  type HttpChatTransportInitOptions,
  type UIMessage,
  type UIMessageChunk,
} from "ai";

import {
  type ProtocolChunk,
  isKnownChunkKind,
  parseChunk,
  readString,
} from "../core/chunks.ts";
import {
  type CursorStore,
  recordFrameCursor,
  tailUrl,
  webStorageCursorStore,
} from "../core/cursor.ts";
import { HANDLED_ENVELOPE_KINDS } from "../core/snapshot.ts";
import { type Frame, isComment, isDone, readFrames } from "../core/sse.ts";

const NO_TURN_IN_FLIGHT = 204;

export interface DurableChatTransportOptions<
  UI_MESSAGE extends UIMessage,
> extends HttpChatTransportInitOptions<UI_MESSAGE> {
  conversationId: string;
  eventsUrlFor: (conversationId: string) => string;
  cursors?: CursorStore;
  /** Called with a chunk this client cannot place, which section 5 says to ignore. */
  onUnhandledChunk?: (chunk: unknown) => void;
}

interface HeldTurn {
  messageId: string;
  head: Frame;
  rest: AsyncGenerator<Frame>;
}

/** What the last reconnect was made with, reused by a chained tail. */
interface ReconnectInit {
  headers: HeadersInit | undefined;
  credentials: RequestCredentials | undefined;
  signal: AbortSignal | undefined;
  after: number;
}

/** How one read relates to the message the client already holds. */
export interface Replay {
  resuming: boolean;
  /** The message to replay, and the only one this stream may carry first. */
  messageId: string | undefined;
  /** The last cursor the client observed, buffered rather than streamed. */
  through: number;
}

async function* framesFrom(
  head: Frame,
  rest: AsyncGenerator<Frame>,
): AsyncGenerator<Frame> {
  yield head;
  yield* rest;
}

function opensMessage(chunk: ProtocolChunk | undefined): string | undefined {
  return chunk?.type === "start" ? readString(chunk, "messageId") : undefined;
}

/**
 * A chat transport over the durable event log. It replays a message a turn left
 * open from that message's own `start`, across as many tails as the host serves,
 * and holds the next `start` for the resume that opens its message.
 */
export class DurableChatTransport<
  UI_MESSAGE extends UIMessage,
> extends DefaultChatTransport<UI_MESSAGE> {
  private readonly conversationId: string;
  private readonly eventsUrl: string;
  private readonly cursors: CursorStore;
  private readonly reconnectInit: ReconnectInit;
  private readonly onUnhandledChunk: ((chunk: unknown) => void) | undefined;
  private resuming = false;
  private held: HeldTurn | undefined;

  constructor(options: DurableChatTransportOptions<UI_MESSAGE>) {
    const { conversationId, eventsUrlFor, cursors, onUnhandledChunk, ...base } =
      options;
    const store = cursors ?? webStorageCursorStore();
    const eventsUrl = eventsUrlFor(conversationId);
    const init: ReconnectInit = {
      headers: undefined,
      credentials: undefined,
      signal: undefined,
      after: 0,
    };
    super({
      ...base,
      prepareReconnectToStreamRequest: ({ headers, credentials }) => {
        init.headers = headers;
        init.credentials = credentials;
        const open = store.readOpenMessage(conversationId);
        init.after = open?.after ?? store.read(conversationId);
        const request: {
          api: string;
          headers?: HeadersInit;
          credentials?: RequestCredentials;
        } = {
          api: tailUrl(eventsUrl, init.after),
        };
        if (headers !== undefined) request.headers = headers;
        if (credentials !== undefined) request.credentials = credentials;
        return request;
      },
    });
    this.conversationId = conversationId;
    this.eventsUrl = eventsUrl;
    this.cursors = store;
    this.reconnectInit = init;
    this.onUnhandledChunk = onUnhandledChunk;
  }

  /** The message the last resume stopped at, to be opened before the next one. */
  takeHeldTurn(): string | undefined {
    return this.held?.messageId;
  }

  /** Read the tail after `cursor`, or nothing when no turn is in flight. */
  private async tailBody(cursor: number): Promise<ReadableStream<Uint8Array> | null> {
    const fetchImpl = this.fetch ?? globalThis.fetch;
    const url = tailUrl(this.eventsUrl, cursor);
    const response = await fetchImpl(url, {
      method: "GET",
      ...(this.reconnectInit.headers === undefined
        ? {}
        : { headers: this.reconnectInit.headers }),
      ...(this.reconnectInit.credentials === undefined
        ? {}
        : { credentials: this.reconnectInit.credentials }),
      ...(this.reconnectInit.signal === undefined
        ? {}
        : { signal: this.reconnectInit.signal }),
    });
    if (response.status === NO_TURN_IN_FLIGHT) return null;
    if (!response.ok) {
      throw new Error(`assistant tail failed: ${String(response.status)} ${url}`);
    }
    return response.body;
  }

  /**
   * One stream across the tail boundaries a host serves, while a message is open.
   * The chain ends where a response does not carry the thread past its request,
   * so a host that re-serves one `done` cannot hold the client in a loop.
   */
  private async *tailChain(
    initial: AsyncGenerator<Frame>,
    from: number,
  ): AsyncGenerator<Frame> {
    let frames = initial;
    let requested = from;
    let cursor = 0;
    for (;;) {
      let endedOnDone = false;
      for (;;) {
        const next = await frames.next();
        if (next.done === true) break;
        cursor = next.value.eventId ?? cursor;
        endedOnDone = isDone(next.value);
        yield next.value;
      }
      if (!endedOnDone) return;
      if (this.cursors.readOpenMessage(this.conversationId) === undefined) return;
      if (cursor <= requested) return;
      const body = await this.tailBody(cursor);
      if (body === null) return;
      requested = cursor;
      frames = readFrames(body, { allowTruncatedTail: true });
    }
  }

  /** Re-frame the payloads this client accepted, for the SDK's own reader. */
  protected acceptedPayloads(
    frames: AsyncGenerator<Frame>,
    replay: Replay,
  ): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    let awaiting = replay.messageId;
    let current = replay.messageId;
    // The prefix the client already holds reaches the SDK as one write, so the
    // message it rebuilds from empty state is never read back half built.
    let replayed: string[] | undefined = replay.through > 0 ? [] : undefined;
    return new ReadableStream<Uint8Array>({
      start: async (controller) => {
        const flush = (): void => {
          if (replayed === undefined) return;
          const buffered = replayed;
          replayed = undefined;
          if (buffered.length > 0)
            controller.enqueue(encoder.encode(buffered.join("")));
        };
        try {
          for (;;) {
            const next = await frames.next();
            if (next.done === true) break;
            const frame = next.value;
            if (isComment(frame) || frame.data === undefined) continue;
            if (frame.eventId === undefined || frame.eventId > replay.through) flush();
            const chunk = isDone(frame) ? undefined : parseChunk(frame.data);
            const opens = opensMessage(chunk);
            if (awaiting !== undefined) {
              if (opens !== awaiting) continue;
              awaiting = undefined;
            }
            recordFrameCursor(this.cursors, this.conversationId, frame, chunk);
            if (chunk === undefined || HANDLED_ENVELOPE_KINDS.has(chunk.type)) continue;
            if (!isKnownChunkKind(chunk.type)) {
              this.onUnhandledChunk?.(chunk);
              continue;
            }
            if (
              replay.resuming &&
              opens !== undefined &&
              current !== undefined &&
              opens !== current
            ) {
              flush();
              this.held = { messageId: opens, head: frame, rest: frames };
              controller.close();
              return;
            }
            if (opens !== undefined) current = opens;
            const payload = `data: ${frame.data}\n\n`;
            if (replayed !== undefined) replayed.push(payload);
            else controller.enqueue(encoder.encode(payload));
          }
          flush();
          controller.close();
        } catch (err) {
          controller.error(err);
        }
      },
    });
  }

  private reader(
    frames: AsyncGenerator<Frame>,
    replay: Replay,
  ): ReadableStream<UIMessageChunk> {
    return super.processResponseStream(this.acceptedPayloads(frames, replay));
  }

  override async reconnectToStream(
    options: Parameters<DefaultChatTransport<UI_MESSAGE>["reconnectToStream"]>[0],
  ): Promise<ReadableStream<UIMessageChunk> | null> {
    this.reconnectInit.signal = options.abortSignal;
    const held = this.held;
    if (held !== undefined) {
      this.held = undefined;
      return this.reader(framesFrom(held.head, held.rest), {
        resuming: true,
        messageId: held.messageId,
        through: 0,
      });
    }
    this.resuming = true;
    try {
      return await super.reconnectToStream(options);
    } finally {
      this.resuming = false;
    }
  }

  protected override processResponseStream(
    stream: ReadableStream<Uint8Array<ArrayBufferLike>>,
  ): ReadableStream<UIMessageChunk> {
    const frames = readFrames(stream, { allowTruncatedTail: true });
    if (!this.resuming) {
      return this.reader(frames, { resuming: false, messageId: undefined, through: 0 });
    }
    const messageId = this.cursors.readOpenMessage(this.conversationId)?.messageId;
    return this.reader(this.tailChain(frames, this.reconnectInit.after), {
      resuming: true,
      messageId,
      through: messageId === undefined ? 0 : this.cursors.read(this.conversationId),
    });
  }
}
