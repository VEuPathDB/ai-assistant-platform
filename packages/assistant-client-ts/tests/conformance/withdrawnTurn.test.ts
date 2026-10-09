import { describe, expect, it } from "vitest";

import { reduceSnapshot } from "../../src/core/snapshot.ts";
import { type Trace, buildTrace } from "../../src/core/trace.ts";
import { type MessagePart } from "../../src/core/message.ts";

const NOTICE = "The model declined this request. Try rephrasing it.";

function userEnvelope(id: string, text: string): unknown {
  return {
    type: "user-message",
    message: { id, role: "user", parts: [{ type: "text", text }] },
  };
}

function withdrawn(messageId: string): MessagePart {
  return { type: "data-turn-withdrawn", data: { errorText: NOTICE, messageId } };
}

function answeredTurn(messageId: string, text: string): unknown[] {
  return [
    { type: "start", messageId },
    { type: "text-start", id: `${messageId}-t` },
    { type: "text-delta", id: `${messageId}-t`, delta: text },
    { type: "text-end", id: `${messageId}-t` },
    { type: "finish", finishReason: "stop" },
    { type: "done" },
  ];
}

function declinedTurn(messageId: string, promptId: string): unknown[] {
  return [
    { type: "start", messageId },
    { type: "reasoning-start", id: "r" },
    { type: "reasoning-delta", id: "r", delta: "thinking about it" },
    { type: "reasoning-end", id: "r" },
    { type: "error", errorText: NOTICE },
    withdrawn(promptId),
    { type: "finish", finishReason: "stop" },
    { type: "done" },
  ];
}

describe("section 9, a withdrawn turn", () => {
  const thread = reduceSnapshot([
    userEnvelope("u1", "Which sites hold kinases?"),
    ...answeredTurn("a1", "PlasmoDB."),
    userEnvelope("u2", "the refused prompt"),
    ...declinedTurn("a2", "u2"),
    userEnvelope("u3", "And phosphatases?"),
    ...answeredTurn("a3", "ToxoDB."),
  ]);

  it("removes the prompt the turn withdraws and keeps every other message", () => {
    expect(thread.map((message) => message.id)).toEqual(["u1", "a1", "a2", "u3", "a3"]);
  });

  it("shows the declined turn as its withdrawn part alone", () => {
    expect(thread.find((message) => message.id === "a2")?.parts).toEqual([
      withdrawn("u2"),
    ]);
  });

  it("reduces the turn after it as any other turn", () => {
    expect(thread.find((message) => message.id === "a3")?.parts).toEqual([
      { type: "text", text: "ToxoDB.", state: "done" },
    ]);
  });

  it("removes the named prompt when the log holds it after the turn", () => {
    const late = reduceSnapshot([
      ...declinedTurn("a2", "u2"),
      userEnvelope("u2", "late"),
    ]);

    expect(late.map((message) => message.id)).toEqual(["a2"]);
  });

  it("keeps every prompt when a resumed turn withdraws its run alone", () => {
    const run: MessagePart = {
      type: "data-turn-withdrawn",
      data: { errorText: NOTICE },
    };
    const resumed = reduceSnapshot([
      userEnvelope("u1", "Run the control tests."),
      ...answeredTurn("a1", "Started."),
      { type: "start", messageId: "a2" },
      { type: "reasoning-start", id: "r" },
      { type: "reasoning-delta", id: "r", delta: "reading the results" },
      { type: "reasoning-end", id: "r" },
      run,
      { type: "error", errorText: NOTICE },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(resumed.map((message) => message.id)).toEqual(["u1", "a1", "a2"]);
    expect(resumed.find((message) => message.id === "a2")?.parts).toEqual([run]);
  });
});

describe("section 6, a withdrawn turn closes its open work", () => {
  it("reads an open dispatch as failed", () => {
    const parts: MessagePart[] = [
      {
        type: "data-sub-agent-call",
        id: "sa_1",
        data: {
          toolCallId: "sa_1",
          subAgent: "checker",
          phase: "review",
          state: "started",
        },
      },
      {
        type: "data-sub-agent-step",
        data: {
          parentToolCallId: "sa_1",
          kind: "tool",
          state: "started",
          toolCallId: "s1",
          toolName: "fetch_rows",
          args: {},
        },
      },
      withdrawn("u2"),
    ];
    const runs: Trace[] = buildTrace(parts);

    expect(runs[0]?.groups[0]?.state).toBe("failed");
  });
});
