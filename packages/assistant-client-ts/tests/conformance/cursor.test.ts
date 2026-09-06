import { beforeEach, describe, expect, it } from "vitest";

import {
  memoryCursorStore,
  recordFrameCursor,
  tailUrl,
  webStorageCursorStore,
} from "../../src/core/cursor.ts";
import {
  DONE_PAYLOAD,
  frameText,
  KEEPALIVE_FRAME,
  parseFrame,
} from "../../src/core/sse.ts";

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

    recordFrameCursor(store, "c1", parseFrame(frameText(12, DONE_PAYLOAD)));

    expect(store.read("c1")).toBe(12);
  });

  it("does not advance mid-turn, because a resumed part needs its start chunk", () => {
    const store = memoryCursorStore();

    recordFrameCursor(store, "c1", parseFrame(frameText(3, '{"type":"text-delta"}')));

    expect(store.read("c1")).toBe(0);
  });

  it("does not advance on a comment frame", () => {
    const store = memoryCursorStore();
    store.write("c1", 5);

    recordFrameCursor(store, "c1", parseFrame(KEEPALIVE_FRAME));

    expect(store.read("c1")).toBe(5);
  });

  it("never moves backwards", () => {
    const store = memoryCursorStore();
    store.write("c1", 20);

    recordFrameCursor(store, "c1", parseFrame(frameText(12, DONE_PAYLOAD)));

    expect(store.read("c1")).toBe(20);
  });

  it("does not assume the next cursor is one more", () => {
    const store = memoryCursorStore();

    recordFrameCursor(store, "c1", parseFrame(frameText(4, DONE_PAYLOAD)));
    recordFrameCursor(store, "c1", parseFrame(frameText(97, DONE_PAYLOAD)));

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
});
