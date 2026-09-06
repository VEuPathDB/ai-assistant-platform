import {
  DefaultChatTransport,
  type HttpChatTransportInitOptions,
  type UIMessage,
  type UIMessageChunk,
} from "ai";

import { isKnownChunkKind, parseChunk, readString } from "../core/chunks.ts";
import {
  type CursorStore,
  recordFrameCursor,
  tailUrl,
  webStorageCursorStore,
} from "../core/cursor.ts";
import { HANDLED_ENVELOPE_KINDS } from "../core/snapshot.ts";
import { type Frame, isComment, isDone, readFrames } from "../core/sse.ts";

export interface DurableChatTransportOptions<
  UI_MESSAGE extends UIMessage,
> extends HttpChatTransportInitOptions<UI_MESSAGE> {
  conversationId: string;
  eventsUrlFor: (conversationId: string) => string;
  cursors?: CursorStore;
  /** The assistant message this client already holds, if the thread has one. */
  openMessageId?: string;
  /** Called with a chunk this client cannot place, which section 5 says to ignore. */
  onUnhandledChunk?: (chunk: unknown) => void;
}

interface HeldTurn {
  messageId: string;
  head: Frame;
  rest: AsyncGenerator<Frame>;
}

async function* framesFrom(
  head: Frame,
  rest: AsyncGenerator<Frame>,
): AsyncGenerator<Frame> {
  yield head;
  yield* rest;
}

/**
 * A chat transport over the durable event log. It resumes from the cursor it
 * holds, reads the frames section 3 defines, and drops what a client of this
 * protocol version must ignore before the SDK's chunk schema sees it.
 *
 * The SDK builds one message per stream, and a resumed stream continues the
 * message the client already holds. A `start` chunk that names another message
 * therefore ends the stream: the transport holds the rest of the tail and
 * serves it to the next resume, so no part of one message reaches the next.
 */
export class DurableChatTransport<
  UI_MESSAGE extends UIMessage,
> extends DefaultChatTransport<UI_MESSAGE> {
  private readonly conversationId: string;
  private readonly cursors: CursorStore;
  private readonly onUnhandledChunk: ((chunk: unknown) => void) | undefined;
  private openMessageId: string | undefined;
  private resuming = false;
  private held: HeldTurn | undefined;

  constructor(options: DurableChatTransportOptions<UI_MESSAGE>) {
    const {
      conversationId,
      eventsUrlFor,
      cursors,
      openMessageId,
      onUnhandledChunk,
      ...base
    } = options;
    const store = cursors ?? webStorageCursorStore();
    super({
      ...base,
      prepareReconnectToStreamRequest: ({ headers, credentials }) => {
        const request: {
          api: string;
          headers?: HeadersInit;
          credentials?: RequestCredentials;
        } = {
          api: tailUrl(eventsUrlFor(conversationId), store.read(conversationId)),
        };
        if (headers !== undefined) request.headers = headers;
        if (credentials !== undefined) request.credentials = credentials;
        return request;
      },
    });
    this.conversationId = conversationId;
    this.cursors = store;
    this.openMessageId = openMessageId;
    this.onUnhandledChunk = onUnhandledChunk;
  }

  /** The message the last resume stopped at, to be opened before the next one. */
  takeHeldTurn(): string | undefined {
    return this.held?.messageId;
  }

  /** Re-frame the payloads this client accepted, for the SDK's own reader. */
  private acceptedPayloads(
    frames: AsyncGenerator<Frame>,
    resuming: boolean,
  ): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream<Uint8Array>({
      start: async (controller) => {
        try {
          for (;;) {
            const next = await frames.next();
            if (next.done === true) break;
            const frame = next.value;
            recordFrameCursor(this.cursors, this.conversationId, frame);
            if (isComment(frame) || isDone(frame) || frame.data === undefined) continue;
            const chunk = parseChunk(frame.data);
            if (chunk === undefined || HANDLED_ENVELOPE_KINDS.has(chunk.type)) continue;
            if (!isKnownChunkKind(chunk.type)) {
              this.onUnhandledChunk?.(chunk);
              continue;
            }
            const opens =
              chunk.type === "start" ? readString(chunk, "messageId") : undefined;
            if (
              resuming &&
              opens !== undefined &&
              this.openMessageId !== undefined &&
              opens !== this.openMessageId
            ) {
              this.held = { messageId: opens, head: frame, rest: frames };
              controller.close();
              return;
            }
            if (opens !== undefined) this.openMessageId = opens;
            controller.enqueue(encoder.encode(`data: ${frame.data}\n\n`));
          }
          controller.close();
        } catch (err) {
          controller.error(err);
        }
      },
    });
  }

  private reader(
    frames: AsyncGenerator<Frame>,
    resuming: boolean,
  ): ReadableStream<UIMessageChunk> {
    return super.processResponseStream(this.acceptedPayloads(frames, resuming));
  }

  override async reconnectToStream(
    options: Parameters<DefaultChatTransport<UI_MESSAGE>["reconnectToStream"]>[0],
  ): Promise<ReadableStream<UIMessageChunk> | null> {
    const held = this.held;
    if (held !== undefined) {
      this.held = undefined;
      this.openMessageId = held.messageId;
      return this.reader(framesFrom(held.head, held.rest), true);
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
    return this.reader(readFrames(stream, { allowTruncatedTail: true }), this.resuming);
  }
}
