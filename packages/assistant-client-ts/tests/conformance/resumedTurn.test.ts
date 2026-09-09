import { describe, expect, it } from "vitest";

import { memoryCursorStore } from "../../src/core/cursor.ts";
import {
  RESUMED,
  RESUSPENDED,
  RESUSPENDED_DONE,
  RESUSPENDED_PARTS,
  SUSPENDED,
  SUSPENDED_DONE,
  SUSPENDED_PARTS,
  SUSPENDED_START,
  SUSPENDED_THREAD,
  SUSPENDING_TAIL,
  SUSPENDING_TURN,
  TWICE_SUSPENDED_THREAD,
  bodyOf,
  harness,
  heldSuspendedMessage,
  logOf,
  seedSuspended,
  sseResponse,
  tailFrom,
} from "./durableResume.ts";

describe("a tail that crosses a turn boundary", () => {
  it("reads the continuation as its own message, and copies no part into it", async () => {
    const probe = harness({ thread: SUSPENDED_THREAD, post: SUSPENDING_TAIL });

    await probe.chat.sendMessage({ text: "optimize the search parameters" });
    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: probe.chat.messages[0]?.id ?? "", role: "user", parts: ["text"] },
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("opens the next tail itself where the host ended one at a done", async () => {
    const probe = harness({ thread: SUSPENDED_THREAD, post: SUSPENDING_TAIL });

    await probe.chat.sendMessage({ text: "optimize the search parameters" });
    await probe.resume();

    expect(probe.urls).toEqual([
      "/api/v1/chat",
      "/api/v1/conversations/c1/events?after=0",
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_DONE)}`,
    ]);
  });

  it("finds the boundary from the message a reload already holds", async () => {
    const probe = harness({
      thread: SUSPENDED_THREAD,
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
    });

    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("stops the chain where the host says no turn is in flight", async () => {
    const probe = harness({
      thread: SUSPENDED_THREAD.slice(0, SUSPENDING_TURN.length),
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
    });

    await probe.resume();

    expect(probe.urls).toEqual([
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_DONE)}`,
    ]);
    expect(probe.shape()).toEqual([
      { id: SUSPENDED, role: "assistant", parts: ["data-background-task-started"] },
    ]);
  });

  it("carries the reconnect's headers and abort signal onto the tail it opens", async () => {
    const probe = harness({
      thread: SUSPENDED_THREAD,
      headers: { authorization: "Bearer token" },
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
    });

    await probe.resume();

    const opened = probe.requests[0]?.init;
    const chained = probe.requests[1]?.init;
    expect(new Headers(chained?.headers).get("authorization")).toBe("Bearer token");
    expect(chained?.signal).toBe(opened?.signal);
    expect(chained?.signal).toBeInstanceOf(AbortSignal);
  });

  it("reads a second suspension the hand-off turn opens", async () => {
    const probe = harness({
      thread: TWICE_SUSPENDED_THREAD,
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
    });

    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: SUSPENDED, role: "assistant", parts: SUSPENDED_PARTS },
      { id: RESUSPENDED, role: "assistant", parts: RESUSPENDED_PARTS },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
    expect(probe.urls).toEqual([
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_DONE)}`,
      `/api/v1/conversations/c1/events?after=${String(RESUSPENDED_DONE)}`,
    ]);
  });

  it("aborts a tail the hand-off opens with the turn that owns it", async () => {
    let reached = (): void => undefined;
    const opened = new Promise<void>((resolve) => {
      reached = resolve;
    });
    let seen: RequestInit | undefined;
    let served = 0;
    const probe = harness({
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
      respond: (after, init) => {
        served += 1;
        if (served < 3) return tailFrom(TWICE_SUSPENDED_THREAD, after);
        seen = init;
        reached();
        return sseResponse(new ReadableStream<Uint8Array>({ start: () => undefined }));
      },
    });

    const running = probe.resume();
    await opened;
    await probe.chat.stop();
    await running;

    expect(seen?.signal?.aborted).toBe(true);
  });

  it("stops the chain where a host re-serves the same done", async () => {
    const repeated = bodyOf(SUSPENDING_TAIL);
    const probe = harness({
      cursors: seedSuspended(memoryCursorStore(), {
        after: SUSPENDED_START,
        done: SUSPENDED_DONE,
      }),
      holds: [heldSuspendedMessage()],
      respond: () => sseResponse(repeated),
    });

    await probe.resume();

    expect(probe.urls).toEqual([
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_START)}`,
      `/api/v1/conversations/c1/events?after=${String(SUSPENDED_DONE)}`,
    ]);
  });

  it("keeps a resumed stream that opens the turn on one message", async () => {
    const probe = harness({
      thread: logOf([
        { type: "start", messageId: RESUMED },
        { type: "text-start", id: "c1" },
        { type: "text-delta", id: "c1", delta: "Still working." },
      ]),
    });

    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
    expect(probe.urls).toEqual(["/api/v1/conversations/c1/events?after=0"]);
  });

  it("ends when the thread has no turn in flight", async () => {
    const probe = harness();

    await probe.resume();

    expect(probe.shape()).toEqual([]);
  });
});
