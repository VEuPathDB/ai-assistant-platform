import { describe, expect, it } from "vitest";

import { type MessagePart } from "../../src/core/message.ts";
import { type Trace, buildTrace } from "../../src/core/trace.ts";

const FIGURES: ReadonlySet<string> = new Set(["data-gene-set", "data-strategy-link"]);

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
    input: {},
    output: {},
  };
}

function text(body: string): MessagePart {
  return { type: "text", text: body, state: "done" };
}

describe("buildTrace run boundaries", () => {
  it("closes the open run on a text part", () => {
    const traces = runs([
      call("get_strategy", "c1"),
      text("Done."),
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces.map((run) => run.rowCount)).toEqual([1, 1]);
  });

  it("keeps the run open across a reasoning part", () => {
    const traces = runs([
      call("get_strategy", "c1"),
      { type: "reasoning", text: "weighing it", state: "done" },
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces.map((run) => run.rowCount)).toEqual([2]);
  });

  it("keeps the run open across a text part that carries nothing", () => {
    const traces = runs([
      call("get_strategy", "c1"),
      { type: "text", text: "", state: "done" },
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces.map((run) => run.rowCount)).toEqual([2]);
  });

  it("closes nothing on a turn-status part", () => {
    const traces = runs([
      call("get_strategy", "c1"),
      { type: "data-turn-status", data: { label: "Thinking...", waitingOnLlm: true } },
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(1);
    expect(at(traces, 0).rowCount).toBe(2);
  });

  it("closes nothing on a step-start part", () => {
    const traces = runs([
      call("get_strategy", "c1"),
      { type: "step-start" },
      call("think", "c2"),
    ]);

    expect(traces).toHaveLength(1);
    expect(at(traces, 0).rowCount).toBe(2);
  });

  it("emits no run for a text part that closes an empty one", () => {
    expect(runs([text("Hello."), text("Still here.")])).toEqual([]);
  });

  it("opens no run for a trailing text part after the last run", () => {
    const traces = runs([call("get_strategy", "c1"), text("That is all.")]);

    expect(traces).toHaveLength(1);
    expect(at(traces, 0).rowCount).toBe(1);
  });
});
