import { type ProtocolChunk, asRecord, readString } from "./chunks.ts";
import { type Frame, isComment, isDone } from "./sse.ts";

/** The message a thread is building, and the cursor a tail replays it from. */
export interface OpenMessage {
  readonly messageId: string;
  readonly after: number;
}

export interface CursorStore {
  read(threadId: string): number;
  write(threadId: string, cursor: number): void;
  readOpenMessage(threadId: string): OpenMessage | undefined;
  writeOpenMessage(threadId: string, open: OpenMessage | undefined): void;
}

/** Add the exclusive `after` bound section 4 defines. */
export function tailUrl(eventsUrl: string, cursor: number): string {
  const separator = eventsUrl.includes("?") ? "&" : "?";
  return `${eventsUrl}${separator}after=${String(cursor)}`;
}

/** Section 6: a turn that ends any other way sends its message nothing more. */
const SUSPENDED_TURN = "other";

function advance(store: CursorStore, threadId: string, frame: Frame): void {
  const cursor = frame.eventId;
  if (cursor === undefined || cursor <= store.read(threadId)) return;
  store.write(threadId, cursor);
}

function openMessage(store: CursorStore, threadId: string, chunk: ProtocolChunk): void {
  const messageId = readString(chunk, "messageId");
  if (messageId === undefined) return;
  if (store.readOpenMessage(threadId)?.messageId === messageId) return;
  store.writeOpenMessage(threadId, { messageId, after: store.read(threadId) });
}

/** Persist a turn terminator's cursor, and the message a `start` leaves open. */
export function recordFrameCursor(
  store: CursorStore,
  threadId: string,
  frame: Frame,
  chunk: ProtocolChunk | undefined,
): void {
  if (isComment(frame)) return;
  if (isDone(frame)) {
    advance(store, threadId, frame);
    return;
  }
  if (chunk === undefined) return;
  if (chunk.type === "start") openMessage(store, threadId, chunk);
  else if (
    chunk.type === "finish" &&
    readString(chunk, "finishReason") !== SUSPENDED_TURN
  ) {
    store.writeOpenMessage(threadId, undefined);
  }
}

export function memoryCursorStore(): CursorStore {
  const cursors = new Map<string, number>();
  const messages = new Map<string, OpenMessage>();
  return {
    read: (threadId) => cursors.get(threadId) ?? 0,
    write: (threadId, cursor) => {
      cursors.set(threadId, cursor);
    },
    readOpenMessage: (threadId) => messages.get(threadId),
    writeOpenMessage: (threadId, message) => {
      if (message === undefined) messages.delete(threadId);
      else messages.set(threadId, message);
    },
  };
}

export interface WebStorageCursorStoreOptions {
  prefix?: string;
  storage?: () => Storage | null;
}

const DEFAULT_PREFIX = "assistant:event-cursor:";
const OPEN_MESSAGE_INFIX = "open:";

function defaultStorage(): Storage | null {
  return typeof globalThis.sessionStorage === "undefined"
    ? null
    : globalThis.sessionStorage;
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

function parseOpenMessage(raw: string | null | undefined): OpenMessage | undefined {
  if (raw == null) return undefined;
  const record = asRecord(parseJson(raw));
  if (record === undefined) return undefined;
  const messageId = record["messageId"];
  const after = record["after"];
  if (typeof messageId !== "string" || typeof after !== "number") return undefined;
  return { messageId, after };
}

/** A cursor store on Web Storage, inert where no storage exists. */
export function webStorageCursorStore(
  options: WebStorageCursorStoreOptions = {},
): CursorStore {
  const prefix = options.prefix ?? DEFAULT_PREFIX;
  const storage = options.storage ?? defaultStorage;
  const openKey = (threadId: string): string => prefix + OPEN_MESSAGE_INFIX + threadId;
  return {
    read: (threadId) => {
      const raw = storage()?.getItem(prefix + threadId);
      if (raw == null) return 0;
      const cursor = Number.parseInt(raw, 10);
      return Number.isFinite(cursor) && cursor >= 0 ? cursor : 0;
    },
    write: (threadId, cursor) => {
      storage()?.setItem(prefix + threadId, String(cursor));
    },
    readOpenMessage: (threadId) =>
      parseOpenMessage(storage()?.getItem(openKey(threadId))),
    writeOpenMessage: (threadId, message) => {
      if (message === undefined) storage()?.removeItem(openKey(threadId));
      else storage()?.setItem(openKey(threadId), JSON.stringify(message));
    },
  };
}
