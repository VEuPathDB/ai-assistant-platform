import { describe, expect, it } from "vitest";

import type { MessagePart } from "../../src/core/message.ts";
import { buildTrace } from "../../src/core/trace.ts";
import { threadUsage, turnUsage } from "../../src/core/usage.ts";

const MODEL = "openai:gpt-5.6-luna";

function lead(tokens: number, costUsd: string, modelId = MODEL): MessagePart {
  return {
    type: "data-lead-usage",
    id: "lead-usage",
    data: { modelId, tokens, costUsd },
  };
}

function dispatch(
  toolCallId: string,
  tokens: number,
  costUsd: string,
  extra: Record<string, unknown> = {},
): MessagePart {
  return {
    type: "data-sub-agent-call",
    id: toolCallId,
    data: {
      toolCallId,
      subAgent: "build_strategy",
      phase: "build",
      state: "completed",
      tokens,
      costUsd,
      ...extra,
    },
  };
}

function step(parentToolCallId: string): MessagePart {
  return {
    type: "data-sub-agent-step",
    data: {
      parentToolCallId,
      kind: "tool",
      state: "completed",
      toolCallId: "call_inner",
      toolName: "search_genes",
      resultSummary: null,
    },
  };
}

describe("a turn's usage", () => {
  it("keeps the lead's own counts apart from the dispatches it made", () => {
    const usage = turnUsage([
      lead(41_800, "0.0131"),
      dispatch("sa_1", 12_300, "0.004"),
      dispatch("sa_2", 3_200, "0.001"),
    ]);

    expect(usage.lead).toEqual({ tokens: 41_800, costUsd: 0.0131 });
    expect(usage.subAgents).toEqual({ tokens: 15_500, costUsd: 0.005 });
    expect(usage.total.tokens).toBe(57_300);
    expect(usage.total.costUsd).toBeCloseTo(0.0181, 6);
    expect(usage.modelId).toBe(MODEL);
  });

  it("reads the last lead-usage part, which is the one the wire reconciled", () => {
    const usage = turnUsage([lead(50, "0.001"), lead(120, "0.004")]);

    expect(usage.lead).toEqual({ tokens: 120, costUsd: 0.004 });
  });

  it("reports no lead when the turn carries none, and counts the dispatches anyway", () => {
    const usage = turnUsage([dispatch("sa_1", 700, "0.003")]);

    expect(usage.lead).toBe(null);
    expect(usage.modelId).toBe(null);
    expect(usage.total).toEqual({ tokens: 700, costUsd: 0.003 });
  });

  it("counts the tokens the trace's own group line counts", () => {
    const parts = [dispatch("sa_1", 12_300, "0.004"), step("sa_1")];

    const [trace] = buildTrace(parts);

    expect(trace?.groups[0]?.tokens).toBe(turnUsage(parts).subAgents.tokens);
    expect(trace?.groups[0]?.costUsd).toBe("0.004");
  });

  it("counts a dispatch whose payload names no phase, which the trace groups by its call id", () => {
    const parts = [
      {
        type: "data-sub-agent-call",
        data: { toolCallId: "sa_9", tokens: 400, costUsd: "0.002" },
      },
    ];

    expect(turnUsage(parts).subAgents).toEqual({ tokens: 400, costUsd: 0.002 });
  });

  it("ignores a count the protocol does not type that way", () => {
    const usage = turnUsage([
      { type: "data-lead-usage", data: { tokens: "1000", costUsd: 0.5 } },
      { type: "data-sub-agent-call", data: { toolCallId: "sa_1", tokens: "500" } },
    ]);

    expect(usage.lead).toEqual({ tokens: 0, costUsd: 0 });
    expect(usage.subAgents).toEqual({ tokens: 0, costUsd: 0 });
  });

  it("ignores a payload that is not an object", () => {
    expect(turnUsage([{ type: "data-lead-usage", data: "41800" }]).lead).toBe(null);
  });
});

describe("a thread's usage", () => {
  it("sums every assistant turn, one lead reading per turn", () => {
    const usage = threadUsage([
      {
        role: "assistant",
        parts: [
          lead(1_000, "0.01"),
          dispatch("sa_1", 500, "0.002"),
          dispatch("sa_2", 300, "0.001"),
        ],
      },
      {
        role: "assistant",
        parts: [lead(2_000, "0.02"), dispatch("sa_3", 700, "0.003")],
      },
    ]);

    expect(usage.lead).toEqual({ tokens: 3_000, costUsd: 0.03 });
    expect(usage.subAgents.tokens).toBe(1_500);
    expect(usage.subAgents.costUsd).toBeCloseTo(0.006, 6);
    expect(usage.total.tokens).toBe(4_500);
    expect(usage.total.costUsd).toBeCloseTo(0.036, 6);
  });

  it("counts the reconciled lead part of a turn, not the sum of its writes", () => {
    const usage = threadUsage([
      { role: "assistant", parts: [lead(50, "0.001"), lead(120, "0.004")] },
    ]);

    expect(usage.lead).toEqual({ tokens: 120, costUsd: 0.004 });
  });

  it("reads no usage off a user turn", () => {
    const answer: MessagePart[] = [{ type: "text", text: "hi", state: "done" }];
    const usage = threadUsage([
      { role: "user", parts: [lead(999, "9.99")] },
      { role: "assistant", parts: answer },
    ]);

    expect(usage.total).toEqual({ tokens: 0, costUsd: 0 });
  });
});
