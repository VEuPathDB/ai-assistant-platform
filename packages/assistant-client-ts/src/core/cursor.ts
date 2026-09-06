import { type Frame, isComment, isDone } from "./sse.ts";

export interface CursorStore {
  read(threadId: string): number;
  write(threadId: string, cursor: number): void;
}

/** Add the exclusive `after` bound section 4 defines. */
export function tailUrl(eventsUrl: string, cursor: number): string {
  const separator = eventsUrl.includes("?") ? "&" : "?";
  return `${eventsUrl}${separator}after=${String(cursor)}`;
}

/**
 * Persist a frame's cursor when it closes a turn.
 *
 * A mid-turn cursor names a chunk that addresses parts its `start` chunk
 * opened, so resuming from one hands the client chunks it cannot place.
 */
export function recordFrameCursor(
  store: CursorStore,
  threadId: string,
  frame: Frame,
): void {
  if (isComment(frame) || !isDone(frame)) return;
  const cursor = frame.eventId;
  if (cursor === undefined || cursor <= store.read(threadId)) return;
  store.write(threadId, cursor);
}

export function memoryCursorStore(): CursorStore {
  const cursors = new Map<string, number>();
  return {
    read: (threadId) => cursors.get(threadId) ?? 0,
    write: (threadId, cursor) => {
      cursors.set(threadId, cursor);
    },
  };
}

export interface WebStorageCursorStoreOptions {
  prefix?: string;
  storage?: () => Storage | null;
}

const DEFAULT_PREFIX = "assistant:event-cursor:";

function defaultStorage(): Storage | null {
  return typeof globalThis.sessionStorage === "undefined"
    ? null
    : globalThis.sessionStorage;
}

/** A cursor store on Web Storage, inert where no storage exists. */
export function webStorageCursorStore(
  options: WebStorageCursorStoreOptions = {},
): CursorStore {
  const prefix = options.prefix ?? DEFAULT_PREFIX;
  const storage = options.storage ?? defaultStorage;
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
  };
}
