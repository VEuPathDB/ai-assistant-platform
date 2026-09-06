import { describe, expect, it } from "vitest";

import { HANDLED_ENVELOPE_KINDS, reduceSnapshot } from "../../src/core/snapshot.ts";

function userEnvelope(id: string, text: string): unknown {
  return {
    type: "user-message",
    message: { id, role: "user", parts: [{ type: "text", text }] },
  };
}

describe("section 5.3, envelopes rebuild the prompt side", () => {
  it("names the three kinds the document defines", () => {
    expect([...HANDLED_ENVELOPE_KINDS].sort()).toEqual([
      "assistant-message",
      "system-message",
      "user-message",
    ]);
  });

  it("takes a user message from the log as a whole message", () => {
    expect(reduceSnapshot([userEnvelope("u1", "hello")])).toEqual([
      { id: "u1", role: "user", parts: [{ type: "text", text: "hello" }] },
    ]);
  });

  it("takes a system message from the log", () => {
    const envelope = {
      type: "system-message",
      message: { id: "s1", role: "system", parts: [{ type: "text", text: "rules" }] },
    };

    expect(reduceSnapshot([envelope])).toEqual([
      { id: "s1", role: "system", parts: [{ type: "text", text: "rules" }] },
    ]);
  });

  it("takes a whole assistant message that was not built from deltas", () => {
    const envelope = {
      type: "assistant-message",
      message: {
        id: "a1",
        role: "assistant",
        parts: [{ type: "text", text: "canned" }],
      },
    };

    expect(reduceSnapshot([envelope])).toEqual([
      { id: "a1", role: "assistant", parts: [{ type: "text", text: "canned" }] },
    ]);
  });

  it("never lets an envelope reach the turn reducer", () => {
    const messages = reduceSnapshot([
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t" },
      { type: "text-delta", id: "t", delta: "hi" },
      {
        type: "assistant-message",
        message: { id: "a2", role: "assistant", parts: [] },
      },
    ]);

    expect(messages).toHaveLength(2);
    expect(messages[0]?.parts).toEqual([
      { type: "text", text: "hi", state: "streaming" },
    ]);
    expect(messages[1]?.id).toBe("a2");
  });
});

describe("section 2, a snapshot rebuilds the whole conversation", () => {
  it("orders prompts and answers as the log holds them", () => {
    const messages = reduceSnapshot([
      userEnvelope("u1", "first"),
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "one" },
      { type: "text-end", id: "t1" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
      userEnvelope("u2", "second"),
      { type: "start", messageId: "a2" },
      { type: "text-start", id: "t2" },
      { type: "text-delta", id: "t2", delta: "two" },
      { type: "text-end", id: "t2" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(messages.map((message) => message.id)).toEqual(["u1", "a1", "u2", "a2"]);
    expect(messages[1]?.parts).toEqual([{ type: "text", text: "one", state: "done" }]);
    expect(messages[3]?.parts).toEqual([{ type: "text", text: "two", state: "done" }]);
  });

  it("splits two assistant messages that share no envelope between them", () => {
    const messages = reduceSnapshot([
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "one" },
      { type: "start", messageId: "a2" },
      { type: "text-start", id: "t2" },
      { type: "text-delta", id: "t2", delta: "two" },
    ]);

    expect(messages.map((message) => message.id)).toEqual(["a1", "a2"]);
  });

  it("keeps a status part on the assistant message it precedes", () => {
    const messages = reduceSnapshot([
      { type: "data-turn-status", data: { label: "Queued" } },
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "hello" },
      { type: "text-end", id: "t1" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(messages).toEqual([
      {
        id: "a1",
        role: "assistant",
        errors: [],
        aborted: false,
        finishReason: "stop",
        parts: [
          { type: "data-turn-status", data: { label: "Queued" } },
          { type: "text", text: "hello", state: "done" },
        ],
      },
    ]);
  });

  it("keeps one node per id when the log replays a user message", () => {
    // The shape a regenerate leaves behind: one envelope, an answer, the same
    // envelope again, a second answer.
    const replayed = "43f33eec-e6d5-44bb-b6d3-b367e7dfc888";
    const messages = reduceSnapshot([
      userEnvelope(replayed, "find kinase drug targets"),
      { type: "start", messageId: "5e47a007-a91b-4f64-af61-9216871155c2" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "first attempt" },
      { type: "text-end", id: "t1" },
      { type: "error", errorText: "combine node needs an operator" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
      userEnvelope(replayed, "find kinase drug targets"),
      { type: "start", messageId: "1d25d96f-53e0-4154-a1c9-1454efb439f6" },
      { type: "text-start", id: "t2" },
      { type: "text-delta", id: "t2", delta: "second attempt" },
      { type: "text-end", id: "t2" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(messages.map((message) => message.id)).toEqual([
      replayed,
      "5e47a007-a91b-4f64-af61-9216871155c2",
      "1d25d96f-53e0-4154-a1c9-1454efb439f6",
    ]);
    expect(messages[0]?.parts).toEqual([
      { type: "text", text: "find kinase drug targets" },
    ]);
    expect(messages[2]?.parts).toEqual([
      { type: "text", text: "second attempt", state: "done" },
    ]);
  });

  it("keeps the first message an id names, not the last", () => {
    const messages = reduceSnapshot([
      userEnvelope("u1", "the question"),
      userEnvelope("u1", "a later edit of it"),
    ]);

    expect(messages).toEqual([
      { id: "u1", role: "user", parts: [{ type: "text", text: "the question" }] },
    ]);
  });

  it("merges two turns that share one message id, as it always has", () => {
    // A turn resumed after a durable task reopens with the same `start` id.
    const messages = reduceSnapshot([
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t1" },
      { type: "text-delta", id: "t1", delta: "before" },
      { type: "text-end", id: "t1" },
      { type: "finish", finishReason: "other" },
      { type: "done" },
      { type: "start", messageId: "a1" },
      { type: "text-start", id: "t2" },
      { type: "text-delta", id: "t2", delta: "after" },
      { type: "text-end", id: "t2" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(messages.map((message) => message.id)).toEqual(["a1"]);
    expect(messages[0]?.parts).toEqual([
      { type: "text", text: "before", state: "done" },
      { type: "text", text: "after", state: "done" },
    ]);
  });

  it("reads an empty log as an empty conversation", () => {
    expect(reduceSnapshot([])).toEqual([]);
  });

  it("ignores an entry that is not a chunk", () => {
    expect(reduceSnapshot([null, 7, "text", { noType: true }])).toEqual([]);
  });

  it("drops an envelope that carries no message", () => {
    expect(reduceSnapshot([{ type: "user-message" }])).toEqual([]);
  });
});
