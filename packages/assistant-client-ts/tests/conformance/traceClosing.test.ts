import { describe, expect, it } from "vitest";

import { type MessagePart } from "../../src/core/message.ts";
import { type SubAgentStepPayload } from "../../src/core/subAgentSteps.ts";
import { type Trace, buildTrace } from "../../src/core/trace.ts";

function runs(parts: readonly MessagePart[]): Trace[] {
  return buildTrace(parts);
}

function endedRuns(parts: readonly MessagePart[]): Trace[] {
  return buildTrace(parts, { turnEnded: true });
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
    input: {},
    output: {},
  };
}

function text(body: string): MessagePart {
  return { type: "text", text: body, state: "done" };
}

function dispatch(key: string, done: boolean): MessagePart {
  return {
    type: "data-sub-agent-call",
    id: key,
    data: {
      toolCallId: key,
      subAgent: "verify_strategy",
      phase: "verification",
      state: done ? "completed" : "started",
    },
  };
}

function step(payload: Partial<SubAgentStepPayload>): MessagePart {
  return {
    type: "data-sub-agent-step",
    data: { parentToolCallId: "sa_9", kind: "tool", state: "started", ...payload },
  };
}

describe("buildTrace closes the dispatches a turn left open", () => {
  const STOPPED: MessagePart = { type: "data-turn-stopped", data: {} };
  const FAILED: MessagePart = {
    type: "data-turn-failed",
    data: { errorText: "TimeoutError: the turn ran out of budget" },
  };
  const started = (): MessagePart[] => [
    dispatch("sa_9", false),
    step({ toolCallId: "s1", toolName: "get_estimated_size", args: { step: 132 } }),
  ];

  it("leaves an open dispatch started while the turn still runs", () => {
    const run = at(runs(started()), 0);

    expect(at(run.groups, 0).state).toBe("started");
  });

  it("reads an open dispatch as cancelled when the turn was stopped", () => {
    const run = at(runs([...started(), STOPPED]), 0);

    expect(at(run.groups, 0).state).toBe("cancelled");
  });

  it("reads an open dispatch as failed when the turn failed", () => {
    const run = at(runs([...started(), FAILED]), 0);

    expect(at(run.groups, 0).state).toBe("failed");
  });

  it("reads an open dispatch as superseded when the turn ended saying neither", () => {
    const run = at(endedRuns(started()), 0);

    expect(at(run.groups, 0).state).toBe("superseded");
  });

  it("prefers the stop over the ended turn's own resolution", () => {
    const run = at(endedRuns([...started(), STOPPED]), 0);

    expect(at(run.groups, 0).state).toBe("cancelled");
  });

  it("leaves a dispatch the turn completed alone", () => {
    const run = at(
      endedRuns([
        dispatch("sa_9", true),
        step({ toolCallId: "s1", toolName: "get_estimated_size", args: {} }),
        STOPPED,
      ]),
      0,
    );

    expect(at(run.groups, 0).state).toBe("completed");
  });

  it("stops the rows of a dispatch the turn cancelled", () => {
    const run = at(runs([...started(), STOPPED]), 0);
    const rows = at(run.groups, 0).rows;

    expect(rows.map((row) => row.status)).toEqual(["stopped"]);
    expect(run.running).toBe(false);
    expect(run.rowCount).toBe(1);
  });

  it("stops the rows of a dispatch the turn failed", () => {
    const run = at(runs([...started(), FAILED]), 0);

    expect(at(run.groups, 0).rows.map((row) => row.status)).toEqual(["stopped"]);
    expect(run.running).toBe(false);
  });

  it("leaves the rows of a superseded dispatch running", () => {
    const run = at(endedRuns(started()), 0);

    expect(at(run.groups, 0).state).toBe("superseded");
    expect(at(run.groups, 0).rows.map((row) => row.status)).toEqual(["running"]);
    expect(run.running).toBe(true);
  });

  it("leaves a row that had already answered as it was", () => {
    const run = at(
      runs([
        dispatch("sa_9", false),
        step({ toolCallId: "s1", toolName: "get_estimated_size", args: {} }),
        step({ toolCallId: "s1", state: "completed", resultSummary: "132 records" }),
        step({ toolCallId: "s2", toolName: "think", args: {} }),
        STOPPED,
      ]),
      0,
    );

    expect(at(run.groups, 0).rows.map((row) => row.status)).toEqual(["ok", "stopped"]);
  });

  it("closes no lead group, which owns no dispatch state", () => {
    const run = at(endedRuns([call("get_strategy", "c1"), STOPPED]), 0);

    expect(at(run.groups, 0).key).toBe("lead");
    expect(at(run.groups, 0).state).toBe("started");
  });

  it("closes an open dispatch of every run the message holds", () => {
    const traces = endedRuns([
      ...started(),
      text("One moment."),
      dispatch("sa_10", false),
      step({
        parentToolCallId: "sa_10",
        toolCallId: "s2",
        toolName: "think",
        args: {},
      }),
    ]);

    expect(traces.map((run) => at(run.groups, 0).state)).toEqual([
      "superseded",
      "superseded",
    ]);
  });
});
