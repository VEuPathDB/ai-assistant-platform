import { describe, expect, it } from "vitest";

import { type MessagePart } from "../../src/core/message.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import { type SubAgentStepPayload } from "../../src/core/subAgentSteps.ts";
import { type Trace, buildTrace } from "../../src/core/trace.ts";

function runs(parts: readonly MessagePart[]): Trace[] {
  return buildTrace(parts, { renderingKinds: new Set() });
}

function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`no item at index ${String(index)}`);
  return item;
}

function call(name: string, id: string): MessagePart {
  return {
    type: `tool-${name}`,
    toolCallId: id,
    state: "output-available",
    input: { a: 1 },
    output: { b: 2 },
  };
}

function dispatch(key: string): MessagePart {
  return {
    type: "data-sub-agent-call",
    id: key,
    data: {
      toolCallId: key,
      subAgent: "checker",
      phase: "review",
      state: "completed",
      tokens: 900,
      costUsd: "0.002",
    },
  };
}

function step(payload: Partial<SubAgentStepPayload>): MessagePart {
  return {
    type: "data-sub-agent-step",
    data: { parentToolCallId: "sa_9", kind: "tool", state: "started", ...payload },
  };
}

describe("a call handed back to the model", () => {
  const REFUSED = "records cannot be counted by x";
  const TURN = [
    { type: "start", messageId: "m1" },
    { type: "tool-input-start", toolCallId: "c1", toolName: "count" },
    { type: "tool-input-available", toolCallId: "c1", toolName: "count", input: {} },
    { type: "tool-output-error", toolCallId: "c1", errorText: REFUSED },
    {
      type: "data-tool-summary",
      data: { toolCallId: "c1", summary: REFUSED, status: "corrected" },
    },
  ];

  it("reads as corrected, folded onto the call or beside it", () => {
    const folded = runs(reduceTurn(TURN).parts);
    const beside = runs([
      ...reduceTurn(TURN.filter((chunk) => chunk.type !== "data-tool-summary")).parts,
      {
        type: "data-tool-summary",
        data: { toolCallId: "c1", summary: REFUSED, status: "corrected" },
      },
    ]);

    const row = at(at(at(folded, 0).groups, 0).rows, 0);
    expect(row.status).toBe("corrected");
    expect(row.errorText).toBe(REFUSED);
    expect(beside).toEqual(folded);
  });

  it("reads a failed call with no corrected summary as an error", () => {
    const failed = runs(
      reduceTurn(TURN.filter((chunk) => chunk.type !== "data-tool-summary")).parts,
    );

    expect(at(at(at(failed, 0).groups, 0).rows, 0).status).toBe("error");
  });

  it("leaves a call that answered as it was", () => {
    const traces = runs([
      call("count", "c1"),
      {
        type: "data-tool-summary",
        data: { toolCallId: "c1", summary: REFUSED, status: "corrected" },
      },
    ]);

    expect(at(at(at(traces, 0).groups, 0).rows, 0).status).toBe("ok");
  });

  it("reads a step handed back to its sub-agent as corrected", () => {
    const run = at(
      runs([
        dispatch("sa_9"),
        step({ toolCallId: "s1", toolName: "set_criterion", args: {} }),
        step({ toolCallId: "s1", state: "corrected", resultSummary: "no such search" }),
        step({ toolCallId: "s2", toolName: "set_criterion", args: {} }),
        step({ toolCallId: "s2", state: "failed", resultSummary: "the site failed" }),
      ]),
      0,
    );

    const rows = at(run.groups, 0).rows;
    expect(rows.map((row) => row.status)).toEqual(["corrected", "error"]);
    expect(rows.map((row) => row.errorText)).toEqual([
      "no such search",
      "the site failed",
    ]);
  });
});
