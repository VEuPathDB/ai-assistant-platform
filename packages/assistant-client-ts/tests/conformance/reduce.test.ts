import { describe, expect, it } from "vitest";

import { reduceTurn } from "../../src/core/reduce.ts";
import { type ProtocolChunk } from "../../src/core/chunks.ts";

function turn(...chunks: ProtocolChunk[]): ProtocolChunk[] {
  return chunks;
}

describe("section 9, the message identity", () => {
  it("takes its id from the start chunk", () => {
    const message = reduceTurn(turn({ type: "start", messageId: "m1" }));

    expect(message.id).toBe("m1");
    expect(message.role).toBe("assistant");
  });

  it("merges metadata from message-metadata", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "message-metadata", messageMetadata: { a: 1 } },
        { type: "message-metadata", messageMetadata: { b: 2 } },
      ),
    );

    expect(message.metadata).toEqual({ a: 1, b: 2 });
  });

  it("merges metadata carried on finish", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "message-metadata", messageMetadata: { a: 1 } },
        { type: "finish", finishReason: "stop", messageMetadata: { b: 2 } },
      ),
    );

    expect(message.metadata).toEqual({ a: 1, b: 2 });
  });
});

describe("section 9, text and reasoning parts", () => {
  it("streams a text part and closes it", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "text-start", id: "t1" },
        { type: "text-delta", id: "t1", delta: "hel" },
        { type: "text-delta", id: "t1", delta: "lo" },
        { type: "text-end", id: "t1" },
      ),
    );

    expect(message.parts).toEqual([{ type: "text", text: "hello", state: "done" }]);
  });

  it("leaves an unclosed text part streaming", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "text-start", id: "t1" },
        { type: "text-delta", id: "t1", delta: "hi" },
      ),
    );

    expect(message.parts).toEqual([{ type: "text", text: "hi", state: "streaming" }]);
  });

  it("keeps two text parts apart by id", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "text-start", id: "a" },
        { type: "text-start", id: "b" },
        { type: "text-delta", id: "b", delta: "second" },
        { type: "text-delta", id: "a", delta: "first" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "text", text: "first", state: "streaming" },
      { type: "text", text: "second", state: "streaming" },
    ]);
  });

  it("reduces reasoning by the same rule", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "reasoning-start", id: "r1" },
        { type: "reasoning-delta", id: "r1", delta: "think" },
        { type: "reasoning-end", id: "r1" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "reasoning", text: "think", state: "done" },
    ]);
  });

  it("ignores a delta for a part it does not hold", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "text-delta", id: "gone", delta: "x" },
      ),
    );

    expect(message.parts).toEqual([]);
  });

  it("does not let a text-delta reach a reasoning part with the same id", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "reasoning-start", id: "same" },
        { type: "text-delta", id: "same", delta: "leak" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "reasoning", text: "", state: "streaming" },
    ]);
  });
});

describe("section 9, step boundaries", () => {
  it("appends a step-start part", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "start-step" },
        { type: "text-start", id: "t" },
        { type: "finish-step" },
        { type: "start-step" },
      ),
    );

    expect(message.parts.map((part) => part.type)).toEqual([
      "step-start",
      "text",
      "step-start",
    ]);
  });
});

describe("section 5.2 and 9, data parts", () => {
  it("appends a data part", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "data-turn-status", data: { label: "Preparing context" } },
      ),
    );

    expect(message.parts).toEqual([
      { type: "data-turn-status", data: { label: "Preparing context" } },
    ]);
  });

  it("drops a transient data part, which history must not carry", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        {
          type: "data-turn-usage",
          data: { costUsd: "0", totalTokens: 57 },
          transient: true,
        },
      ),
    );

    expect(message.parts).toEqual([]);
  });

  it("reconciles a data part that carries an id", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "data-sub-agent-call", id: "s1", data: { status: "running" } },
        { type: "data-sub-agent-call", id: "s1", data: { status: "done" } },
      ),
    );

    expect(message.parts).toEqual([
      { type: "data-sub-agent-call", id: "s1", data: { status: "done" } },
    ]);
  });

  it("keeps two ids of the same kind apart", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "data-sub-agent-call", id: "s1", data: { n: 1 } },
        { type: "data-sub-agent-call", id: "s2", data: { n: 2 } },
        { type: "data-sub-agent-call", id: "s1", data: { n: 3 } },
      ),
    );

    expect(message.parts).toEqual([
      { type: "data-sub-agent-call", id: "s1", data: { n: 3 } },
      { type: "data-sub-agent-call", id: "s2", data: { n: 2 } },
    ]);
  });

  it("appends every id-less data part of the same kind", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "data-turn-status", data: { label: "one" } },
        { type: "data-turn-status", data: { label: "two" } },
      ),
    );

    expect(message.parts).toHaveLength(2);
  });
});

describe("section 9, sources and files", () => {
  it("appends a file part", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "file", url: "https://x/y.png", mediaType: "image/png" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "file", url: "https://x/y.png", mediaType: "image/png" },
    ]);
  });

  it("appends a url source part", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "source-url", sourceId: "s", url: "https://x" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "source-url", sourceId: "s", url: "https://x" },
    ]);
  });

  it("appends a document source part", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "source-document", sourceId: "s", mediaType: "text/plain", title: "T" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "source-document", sourceId: "s", mediaType: "text/plain", title: "T" },
    ]);
  });
});

describe("section 5, unknown input", () => {
  it("ignores a chunk kind it does not know", () => {
    const message = reduceTurn(
      turn({ type: "start", messageId: "m1" }, { type: "invented-by-a-later-version" }),
    );

    expect(message.parts).toEqual([]);
  });

  it("ignores unknown fields on a chunk it knows", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "text-start", id: "t", tone: "excited" },
        { type: "text-delta", id: "t", delta: "hi", confidence: 0.9 },
      ),
    );

    expect(message.parts).toEqual([{ type: "text", text: "hi", state: "streaming" }]);
  });

  it("survives a turn with no start chunk", () => {
    const message = reduceTurn(turn({ type: "text-start", id: "t" }));

    expect(message.id).toBe("");
    expect(message.parts).toEqual([{ type: "text", text: "", state: "streaming" }]);
  });
});

describe("section 6, error is not a turn's verdict", () => {
  it("keeps the error chunk's text where a client can find it", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "error", errorText: "the model refused" },
        { type: "finish", finishReason: "stop" },
      ),
    );

    expect(message.errors).toEqual(["the model refused"]);
    expect(message.finishReason).toBe("stop");
  });

  it("reports no error for a clean turn", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "finish", finishReason: "stop" },
      ),
    );

    expect(message.errors).toEqual([]);
  });

  it("keeps the failure of a dead turn as a part a reload can show", () => {
    const errorText = "The worker running this turn stopped before it finished.";
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "a1" },
        { type: "text-start", id: "t" },
        { type: "text-delta", id: "t", delta: "Looking at PlasmoDB kinases" },
        { type: "text-end", id: "t" },
        { type: "error", errorText },
        { type: "data-turn-failed", data: { errorText } },
        { type: "finish", finishReason: "error" },
      ),
    );

    expect(message.parts).toEqual([
      { type: "text", text: "Looking at PlasmoDB kinases", state: "done" },
      { type: "data-turn-failed", data: { errorText } },
    ]);
    expect(message.errors).toEqual([errorText]);
  });
});
