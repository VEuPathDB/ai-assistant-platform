import { describe, expect, it } from "vitest";

import { type MessagePart } from "../../src/core/message.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import {
  type SubAgentStepPayload,
  mergeSubAgentSteps,
} from "../../src/core/subAgentSteps.ts";
import { type Trace, buildTrace } from "../../src/core/trace.ts";

const FIGURES: ReadonlySet<string> = new Set([
  "data-example.rows",
  "data-example.link",
]);

function runs(parts: readonly MessagePart[]): Trace[] {
  return buildTrace(parts, { renderingKinds: FIGURES });
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

function announced(name: string, id: string): MessagePart {
  return { type: `tool-${name}`, toolCallId: id, state: "input-available", input: {} };
}

function awaitingApproval(name: string, id: string): MessagePart {
  return {
    type: `tool-${name}`,
    toolCallId: id,
    state: "approval-requested",
    input: {},
    approval: { id },
  };
}

function dispatch(key: string, done: boolean): MessagePart {
  return {
    type: "data-sub-agent-call",
    id: key,
    data: done
      ? {
          toolCallId: key,
          subAgent: "checker",
          phase: "review",
          state: "completed",
          tokens: 900,
          costUsd: "0.002",
        }
      : {
          toolCallId: key,
          subAgent: "checker",
          phase: "review",
          state: "started",
        },
  };
}

function step(payload: Partial<SubAgentStepPayload>): MessagePart {
  return {
    type: "data-sub-agent-step",
    data: { parentToolCallId: "sa_9", kind: "tool", state: "started", ...payload },
  };
}

describe("buildTrace grouping", () => {
  it("puts a tool part with no group open into the implicit lead group", () => {
    const run = at(runs([call("echo", "c1"), call("think", "c2")]), 0);

    expect(run.groups.map((group) => group.key)).toEqual(["lead"]);
    expect(at(run.groups, 0).phase).toBe("lead");
    expect(at(run.groups, 0).rows.map((row) => row.toolName)).toEqual([
      "echo",
      "think",
    ]);
  });

  it("keys a sub-agent group by its call id and carries its usage and state", () => {
    const run = at(
      runs([call("echo", "c1"), dispatch("sa_9", true), call("think", "c2")]),
      0,
    );
    const group = at(run.groups, 1);

    expect(run.groups.map((each) => each.key)).toEqual(["lead", "sa_9", "lead"]);
    expect(group.phase).toBe("review");
    expect(group.tokens).toBe(900);
    expect(group.costUsd).toBe("0.002");
    expect(group.state).toBe("completed");
  });

  it("merges a sub-agent's started and completed steps into one row each", () => {
    const run = at(
      runs([
        dispatch("sa_9", true),
        step({ toolCallId: "s1", toolName: "fetch_rows", args: { id: 132 } }),
        step({ toolCallId: "s1", state: "completed", resultSummary: "132 rows" }),
        step({ toolCallId: "s2", toolName: "think", args: {} }),
      ]),
      0,
    );
    const rows = at(run.groups, 0).rows;

    expect(rows.map((row) => row.toolName)).toEqual(["fetch_rows", "think"]);
    expect(rows.map((row) => row.summary)).toEqual(["132 rows", null]);
    expect(rows.map((row) => row.status)).toEqual(["ok", "running"]);
    expect(at(rows, 0).input).toEqual({ id: 132 });
  });

  it("drops a step whose parent no group holds", () => {
    const run = at(
      runs([
        dispatch("sa_9", false),
        step({ parentToolCallId: "sa_other", toolCallId: "s1", toolName: "think" }),
        call("echo", "c1"),
      ]),
      0,
    );

    expect(run.rowCount).toBe(1);
  });
});

describe("buildTrace figures and status", () => {
  it("hoists a rendering kind into the run's figures without closing the run", () => {
    const run = at(
      runs([
        call("add", "c1"),
        { type: "data-example.rows", data: { name: "Example" } },
        call("echo", "c2"),
      ]),
      0,
    );

    expect(run.rowCount).toBe(2);
    expect(run.figures.map((figure) => figure.type)).toEqual(["data-example.rows"]);
  });

  it("opens a run holding no row for a figure that arrives alone", () => {
    const traces = runs([{ type: "data-example.rows", data: { name: "Example" } }]);

    expect(traces).toHaveLength(1);
    expect(at(traces, 0).rowCount).toBe(0);
    expect(at(traces, 0).figures).toHaveLength(1);
  });

  it("leaves a non-rendering data part out of the rows and out of the figures", () => {
    const run = at(
      runs([
        call("echo", "c1"),
        { type: "data-turn-usage", data: { totalTokens: 10, costUsd: "0" } },
        { type: "data-example.note", data: {} },
      ]),
      0,
    );

    expect(run.rowCount).toBe(1);
    expect(run.figures).toEqual([]);
  });

  it("reports running while a row waits for its output or for the user", () => {
    const waiting = at(runs([awaitingApproval("add", "c1")]), 0);
    const streaming = at(runs([announced("echo", "c1")]), 0);
    const settled = at(runs([call("echo", "c1")]), 0);

    expect(at(waiting.groups, 0).rows.map((row) => row.status)).toEqual([
      "awaiting-approval",
    ]);
    expect(waiting.running).toBe(true);
    expect(streaming.running).toBe(true);
    expect(settled.running).toBe(false);
  });

  it("reads the tool's own status and its error text onto the row", () => {
    const failed: MessagePart = {
      type: "tool-echo",
      toolCallId: "c2",
      state: "output-error",
      input: {},
      errorText: "the host refused the call",
    };
    const empty: MessagePart = {
      type: "tool-fetch_rows",
      toolCallId: "c1",
      state: "output-available",
      input: {},
      output: { rows: 0 },
      summary: "No row matched",
      summaryStatus: "empty",
    };
    const rows = at(at(runs([empty, failed]), 0).groups, 0).rows;

    expect(rows.map((row) => row.status)).toEqual(["empty", "error"]);
    expect(at(rows, 0).summary).toBe("No row matched");
    expect(at(rows, 1).errorText).toBe("the host refused the call");
  });
});

describe("buildTrace over the two producer shapes", () => {
  const TURN = [
    { type: "start", messageId: "m1" },
    { type: "tool-input-start", toolCallId: "c1", toolName: "fetch_rows" },
    {
      type: "tool-input-available",
      toolCallId: "c1",
      toolName: "fetch_rows",
      input: { query: "example" },
    },
    { type: "tool-output-available", toolCallId: "c1", output: { rows: 3 } },
    {
      type: "data-tool-summary",
      data: { toolCallId: "c1", summary: "3 rows matched", status: "ok" },
    },
  ];

  it("yields one trace whether the summary is folded or sits beside the call", () => {
    const folded = runs(reduceTurn(TURN).parts);
    const beside = runs([
      ...reduceTurn(TURN.filter((chunk) => chunk.type !== "data-tool-summary")).parts,
      {
        type: "data-tool-summary",
        data: { toolCallId: "c1", summary: "3 rows matched", status: "ok" },
      },
    ]);

    expect(beside).toEqual(folded);
    expect(at(at(at(folded, 0).groups, 0).rows, 0).summary).toBe("3 rows matched");
  });

  it("never turns a summary part into a row, a figure or a run boundary", () => {
    const traces = runs([
      call("echo", "c1"),
      { type: "data-tool-summary", data: { toolCallId: "c1", summary: "2 steps" } },
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(1);
    expect(at(traces, 0).rowCount).toBe(2);
    expect(at(traces, 0).figures).toEqual([]);
  });
});

describe("mergeSubAgentSteps", () => {
  function payload(fields: Partial<SubAgentStepPayload>): SubAgentStepPayload {
    return { parentToolCallId: "parent", kind: "tool", state: "started", ...fields };
  }

  it("merges the started args and the completed result into one tool item", () => {
    const items = mergeSubAgentSteps([
      payload({ toolCallId: "t1", toolName: "add", args: { id: "c1" } }),
      payload({ toolCallId: "t1", state: "completed", resultSummary: "c1 added" }),
    ]);

    expect(items).toHaveLength(1);
    const only = at(items, 0);
    expect(only.type).toBe("tool");
    if (only.type !== "tool") throw new Error("the merged item is not a tool");
    expect(only.state).toBe("completed");
    expect(only.args).toEqual({ id: "c1" });
    expect(only.result).toBe("c1 added");
  });

  it("keeps reasoning and text steps as ordered items of their own", () => {
    const items = mergeSubAgentSteps([
      payload({ kind: "reasoning", state: "completed", text: "weighing it" }),
      payload({ toolCallId: "t1", toolName: "think" }),
    ]);

    expect(items.map((item) => item.type)).toEqual(["reasoning", "tool"]);
  });
});
