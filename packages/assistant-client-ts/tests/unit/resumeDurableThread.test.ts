import { type UIMessage } from "ai";
import { describe, expect, it } from "vitest";

import { resumeDurableThread } from "../../src/ai-sdk/resumeDurableThread.ts";

const OPEN = "22222222-2222-2222-2222-222222222222";
const NEXT = "44444444-4444-4444-4444-444444444444";

function message(id: string): UIMessage {
  return { id, role: "assistant", parts: [] };
}

/** A chat that records the ids it holds at the start of every read. */
function chat(held: UIMessage[]) {
  let messages = held;
  const reads: string[][] = [];
  return {
    reads,
    target: {
      setMessages: (update: (thread: UIMessage[]) => UIMessage[]) => {
        messages = update(messages);
      },
      resumeStream: () => {
        reads.push(messages.map((entry) => entry.id));
        return Promise.resolve();
      },
    },
  };
}

function handingOn(turns: string[]) {
  return { takeHeldTurn: () => turns.shift() };
}

describe("a thread read across turn boundaries", () => {
  it("opens the turn a read hands on, so the next read fills it", async () => {
    const probe = chat([message(OPEN)]);

    await resumeDurableThread(probe.target, handingOn([NEXT]));

    expect(probe.reads).toEqual([[OPEN], [OPEN, NEXT]]);
  });

  it("opens no second entry for a turn the thread already holds", async () => {
    const probe = chat([message(OPEN), message(NEXT)]);

    await resumeDurableThread(probe.target, handingOn([NEXT]));

    expect(probe.reads).toEqual([
      [OPEN, NEXT],
      [OPEN, NEXT],
    ]);
  });
});
