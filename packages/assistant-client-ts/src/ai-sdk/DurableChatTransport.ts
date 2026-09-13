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

/** What one read of the tail runs under, until the turn that owns it ends. */
interface TailInit {
  headers: Record<string, string>;
  credentials: RequestCredentials | undefined;
  signal: AbortSignal | undefined;
}

interface HeldTurn {
  messageId: string;
  head: Frame;
  rest: AsyncGenerator<Frame>;
  init: TailInit;
}

/** Takes the turn a read stopped at, with the frames that carry the rest. */
type HoldTurn = (messageId: string, head: Frame, rest: AsyncGenerator<Frame>) => void;

/** How one read relates to the message the client already holds. */
export interface Replay {
  /** The message to replay, and the only one this stream may carry first. */
  messageId: string | undefined;
  /** The last cursor the client observed, buffered rather than streamed. */
  through: number;
  /** Present on a read that may cross into a turn of its own. */
  hold?: HoldTurn;
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

function headerRecord(
  value: Record<string, string> | Headers | undefined,
): Record<string, string> {
  return value === undefined ? {} : Object.fromEntries(new Headers(value).entries());
}

/**
 * A chat transport over the durable event log, with one signal and one chain per
 * read. It replays a message a turn left open whole and holds the next `start`;
 * see `decisions/a-resumed-stream-reads-one-turn.md` for why.
 */
export class DurableChatTransport<
  UI_MESSAGE extends UIMessage,
> extends DefaultChatTransport<UI_MESSAGE> {
  private readonly conversationId: string;
  private readonly eventsUrl: string;
  private readonly cursors: CursorStore;
  private readonly onUnhandledChunk: ((chunk: unknown) => void) | undefined;
  private held: HeldTurn | undefined;

  constructor(options: DurableChatTransportOptions<UI_MESSAGE>) {
    const { conversationId, eventsUrlFor, cursors, onUnhandledChunk, ...base } =
      options;
    super(base);
    this.conversationId = conversationId;
    this.eventsUrl = eventsUrlFor(conversationId);
    this.cursors = cursors ?? webStorageCursorStore();
    this.onUnhandledChunk = onUnhandledChunk;
  }

  /** The message the last resume stopped at, to be opened before the next one. */
  takeHeldTurn(): string | undefined {
    return this.held?.messageId;
  }

  private async tailInit(
    options: Parameters<DefaultChatTransport<UI_MESSAGE>["reconnectToStream"]>[0],
  ): Promise<TailInit> {
    const configured =
      typeof this.headers === "function" ? await this.headers() : await this.headers;
    const credentials =
      typeof this.credentials === "function"
        ? await this.credentials()
        : await this.credentials;
    return {
      headers: { ...headerRecord(configured), ...headerRecord(options.headers) },
      credentials,
      signal: options.abortSignal,
    };
  }

  /** Read the tail after `cursor`, or nothing when no turn is in flight. */
  private async tailBody(
    cursor: number,
    init: TailInit,
  ): Promise<ReadableStream<Uint8Array> | null> {
    const fetchImpl = this.fetch ?? globalThis.fetch;
    const url = tailUrl(this.eventsUrl, cursor);
    const response = await fetchImpl(url, {
      method: "GET",
      headers: init.headers,
      ...(init.credentials === undefined ? {} : { credentials: init.credentials }),
      ...(init.signal === undefined ? {} : { signal: init.signal }),
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
   * so a host that re-serves one `done` cannot hold the client in a loop, and
   * where the turn that owns the read is already over.
   */
  private async *tailChain(
    initial: AsyncGenerator<Frame>,
    from: number,
    init: TailInit,
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
      if (init.signal?.aborted === true) return;
      const body = await this.tailBody(cursor, init);
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
    let reached = 0;
    return new ReadableStream<Uint8Array>({
      start: async (controller) => {
        const flush = (): void => {
          if (replayed === undefined) return;
          const buffered = replayed;
          replayed = undefined;
          if (buffered.length > 0)
            controller.enqueue(encoder.encode(buffered.join("")));
        };
        // A prefix that ends before the cursor the client holds is dropped: it
        // can only rebuild the message with less than the client has.
        const flushReplayed = (): void => {
          if (reached >= replay.through) flush();
        };
        try {
          for (;;) {
            const next = await frames.next();
            if (next.done === true) break;
            const frame = next.value;
            if (isComment(frame) || frame.data === undefined) continue;
            if (frame.eventId === undefined || frame.eventId > replay.through) flush();
            else reached = frame.eventId;
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
              replay.hold !== undefined &&
              opens !== undefined &&
              current !== undefined &&
              opens !== current
            ) {
              flushReplayed();
              replay.hold(opens, frame, frames);
              controller.close();
              return;
            }
            if (opens !== undefined) current = opens;
            const payload = `data: ${frame.data}\n\n`;
            if (replayed !== undefined) replayed.push(payload);
            else controller.enqueue(encoder.encode(payload));
          }
          flushReplayed();
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

  /** A read hands its next turn on, unless the turn that owns the read is over. */
  private holding(init: TailInit): HoldTurn {
    return (messageId, head, rest) => {
      if (init.signal?.aborted === true) return;
      this.held = { messageId, head, rest, init };
    };
  }

  override async reconnectToStream(
    options: Parameters<DefaultChatTransport<UI_MESSAGE>["reconnectToStream"]>[0],
  ): Promise<ReadableStream<UIMessageChunk> | null> {
    const held = this.held;
    this.held = undefined;
    // A chain whose own signal fired carries a body that errors, so the turn
    // that picks a live one up owns what the rest of it runs under.
    if (held !== undefined && held.init.signal?.aborted !== true) {
      held.init.signal = options.abortSignal;
      return this.reader(framesFrom(held.head, held.rest), {
        messageId: held.messageId,
        through: 0,
        hold: this.holding(held.init),
      });
    }
    const init = await this.tailInit(options);
    const open = this.cursors.readOpenMessage(this.conversationId);
    const after = open?.after ?? this.cursors.read(this.conversationId);
    const body = await this.tailBody(after, init);
    if (body === null) return null;
    return this.reader(
      this.tailChain(readFrames(body, { allowTruncatedTail: true }), after, init),
      {
        messageId: open?.messageId,
        through: open === undefined ? 0 : this.cursors.read(this.conversationId),
        hold: this.holding(init),
      },
    );
  }

  protected override processResponseStream(
    stream: ReadableStream<Uint8Array<ArrayBufferLike>>,
  ): ReadableStream<UIMessageChunk> {
    return this.reader(readFrames(stream, { allowTruncatedTail: true }), {
      messageId: undefined,
      through: 0,
    });
  }
}
