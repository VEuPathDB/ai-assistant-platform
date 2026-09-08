import { beforeEach, describe, expect, it } from "vitest";

import { parseChunk } from "../../src/core/chunks.ts";
import {
  type CursorStore,
  memoryCursorStore,
  recordFrameCursor,
  tailUrl,
  webStorageCursorStore,
} from "../../src/core/cursor.ts";
import {
  DONE_PAYLOAD,
  frameText,
  isComment,
  isDone,
  KEEPALIVE_FRAME,
  parseFrame,
} from "../../src/core/sse.ts";

const START = '{"type":"start","messageId":"m1"}';
const CONTINUATION = '{"type":"start","messageId":"m2"}';
const SUSPENDED = '{"type":"finish","finishReason":"other"}';
const COMPLETED = '{"type":"finish","finishReason":"stop"}';
const FAILED = '{"type":"finish","finishReason":"error"}';

/** Record one frame the way a reader of this protocol does. */
function record(store: CursorStore, threadId: string, raw: string): void {
  const frame = parseFrame(raw);
  const carries = !isComment(frame) && !isDone(frame) && frame.data !== undefined;
  recordFrameCursor(
    store,
    threadId,
    frame,
    carries && frame.data !== undefined ? parseChunk(frame.data) : undefined,
  );
}

describe("section 4, after is exclusive", () => {
  it("asks for what follows the cursor it holds", () => {
    expect(tailUrl("/conversations/c1/events", 41)).toBe(
      "/conversations/c1/events?after=41",
    );
  });

  it("asks for the whole thread when it holds nothing", () => {
    expect(tailUrl("/conversations/c1/events", 0)).toBe(
      "/conversations/c1/events?after=0",
    );
  });

  it("keeps a query the caller already put on the url", () => {
    expect(tailUrl("/conversations/c1/events?trace=1", 7)).toBe(
      "/conversations/c1/events?trace=1&after=7",
    );
  });
});

describe("section 4, what a client persists", () => {
  it("advances on a turn terminator", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(12, DONE_PAYLOAD));

    expect(store.read("c1")).toBe(12);
  });

  it("does not advance mid-turn, because a resumed part needs its start chunk", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(3, '{"type":"text-delta"}'));

    expect(store.read("c1")).toBe(0);
  });

  it("does not advance on a comment frame", () => {
    const store = memoryCursorStore();
    store.write("c1", 5);

    record(store, "c1", KEEPALIVE_FRAME);

    expect(store.read("c1")).toBe(5);
  });

  it("never moves backwards", () => {
    const store = memoryCursorStore();
    store.write("c1", 20);

    record(store, "c1", frameText(12, DONE_PAYLOAD));

    expect(store.read("c1")).toBe(20);
  });

  it("does not assume the next cursor is one more", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(4, DONE_PAYLOAD));
    record(store, "c1", frameText(97, DONE_PAYLOAD));

    expect(store.read("c1")).toBe(97);
  });

  it("keeps threads apart", () => {
    const store = memoryCursorStore();

    store.write("c1", 4);
    store.write("c2", 9);

    expect(store.read("c1")).toBe(4);
    expect(store.read("c2")).toBe(9);
  });

  it("reads an unknown thread as the whole thread", () => {
    expect(memoryCursorStore().read("never-seen")).toBe(0);
  });
});

describe("section 4, the message a resume replays", () => {
  it("names the message a start opens, from the boundary before it", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(4, DONE_PAYLOAD));
    record(store, "c1", frameText(9, START));

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m1", after: 4 });
  });

  it("replays the whole thread for the first message it meets", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(9, START));

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m1", after: 0 });
  });

  it("holds a message its turn suspended, because the task reports after done", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c1", frameText(2, SUSPENDED));
    record(store, "c1", frameText(3, DONE_PAYLOAD));

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m1", after: 0 });
  });

  it("closes a message whose turn ran to completion", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c1", frameText(2, COMPLETED));

    expect(store.readOpenMessage("c1")).toBeUndefined();
  });

  it("closes a message whose turn failed", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c1", frameText(2, FAILED));

    expect(store.readOpenMessage("c1")).toBeUndefined();
  });

  it("moves to the message the next turn opens", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c1", frameText(2, SUSPENDED));
    record(store, "c1", frameText(3, DONE_PAYLOAD));
    record(store, "c1", frameText(7, CONTINUATION));

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m2", after: 3 });
  });

  it("writes one message once, so a replay of it moves nothing", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c1", frameText(2, SUSPENDED));
    record(store, "c1", frameText(3, DONE_PAYLOAD));
    record(store, "c1", frameText(1, START));

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m1", after: 0 });
  });

  it("keeps threads apart", () => {
    const store = memoryCursorStore();

    record(store, "c1", frameText(1, START));
    record(store, "c2", frameText(2, CONTINUATION));

    expect(store.readOpenMessage("c1")?.messageId).toBe("m1");
    expect(store.readOpenMessage("c2")?.messageId).toBe("m2");
  });

  it("reads an unknown thread as no open message", () => {
    expect(memoryCursorStore().readOpenMessage("never-seen")).toBeUndefined();
  });
});

describe("the web storage cursor store", () => {
  let entries: Map<string, string>;
  let storage: () => Storage;

  beforeEach(() => {
    entries = new Map();
    storage = () =>
      ({
        getItem: (key: string) => entries.get(key) ?? null,
        setItem: (key: string, value: string) => {
          entries.set(key, value);
        },
        removeItem: (key: string) => {
          entries.delete(key);
        },
      }) as Storage;
  });

  it("round-trips a cursor through storage", () => {
    const store = webStorageCursorStore({ storage });

    store.write("c1", 33);

    expect(store.read("c1")).toBe(33);
  });

  it("namespaces its keys so two hosts do not collide", () => {
    webStorageCursorStore({ storage, prefix: "other:" }).write("c1", 8);

    expect(webStorageCursorStore({ storage }).read("c1")).toBe(0);
    expect(entries.get("other:c1")).toBe("8");
  });

  it("reads a corrupted entry as the whole thread", () => {
    entries.set("assistant:event-cursor:c1", "not a number");

    expect(webStorageCursorStore({ storage }).read("c1")).toBe(0);
  });

  it("reads a negative entry as the whole thread", () => {
    entries.set("assistant:event-cursor:c1", "-4");

    expect(webStorageCursorStore({ storage }).read("c1")).toBe(0);
  });

  it("is inert where no storage exists, so a server render does not throw", () => {
    const store = webStorageCursorStore({ storage: () => null });

    store.write("c1", 5);

    expect(store.read("c1")).toBe(0);
  });

  it("falls back to no storage when the platform has none", () => {
    expect(webStorageCursorStore().read("c1")).toBe(0);
  });

  it("round-trips the open message, so a reload replays it", () => {
    const store = webStorageCursorStore({ storage });

    store.writeOpenMessage("c1", { messageId: "m1", after: 12 });

    expect(store.readOpenMessage("c1")).toEqual({ messageId: "m1", after: 12 });
    expect(
      webStorageCursorStore({ storage, prefix: "other:" }).readOpenMessage("c1"),
    ).toBeUndefined();
  });

  it("forgets the open message when its turn closes it", () => {
    const store = webStorageCursorStore({ storage });
    store.writeOpenMessage("c1", { messageId: "m1", after: 12 });

    store.writeOpenMessage("c1", undefined);

    expect(store.readOpenMessage("c1")).toBeUndefined();
    expect([...entries.keys()]).toEqual([]);
  });

  it("reads a corrupted open message as none", () => {
    entries.set("assistant:event-cursor:open:c1", "{not json");

    expect(webStorageCursorStore({ storage }).readOpenMessage("c1")).toBeUndefined();
  });

  it("reads an open message with no cursor as none", () => {
    entries.set("assistant:event-cursor:open:c1", '{"messageId":"m1"}');

    expect(webStorageCursorStore({ storage }).readOpenMessage("c1")).toBeUndefined();
  });

  it("is inert for the open message where no storage exists", () => {
    const store = webStorageCursorStore({ storage: () => null });

    store.writeOpenMessage("c1", { messageId: "m1", after: 3 });

    expect(store.readOpenMessage("c1")).toBeUndefined();
  });
});
