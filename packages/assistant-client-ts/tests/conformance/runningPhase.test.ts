import { describe, expect, it } from "vitest";

import type { MessagePart, PartLike } from "../../src/core/message.ts";
import { runningPhase } from "../../src/core/dispatch.ts";
import { buildTrace } from "../../src/core/trace.ts";

function dispatch(toolCallId: string, phase: string, state: string): PartLike {
  return { type: "data-sub-agent-call", data: { toolCallId, phase, state } };
}

describe("the phase a turn is running", () => {
  it("names nothing before the first dispatch", () => {
    expect(runningPhase([{ type: "text" }])).toBe(null);
  });

  it("names the phase whose dispatch is still open", () => {
    expect(runningPhase([dispatch("c1", "frame", "started")])).toBe("frame");
  });

  it("names the newer phase once the first one closed", () => {
    expect(
      runningPhase([
        dispatch("c1", "frame", "started"),
        dispatch("c1", "frame", "completed"),
        dispatch("c2", "build", "started"),
      ]),
    ).toBe("build");
  });

  it("names nothing once every dispatch closed", () => {
    expect(
      runningPhase([
        dispatch("c1", "frame", "started"),
        dispatch("c1", "frame", "completed"),
      ]),
    ).toBe(null);
  });

  it("ignores a dispatch that opened without naming a phase", () => {
    expect(
      runningPhase([
        dispatch("c1", "frame", "started"),
        { type: "data-sub-agent-call", data: { toolCallId: "c2", state: "started" } },
      ]),
    ).toBe("frame");
  });

  it("names nothing when the dispatch states an empty phase", () => {
    expect(runningPhase([dispatch("c1", "", "started")])).toBe(null);
  });

  it("leaves the trace to group an empty phase under its call id", () => {
    const parts: MessagePart[] = [
      {
        type: "data-sub-agent-call",
        data: { toolCallId: "c1", phase: "", state: "started" },
      },
      {
        type: "data-sub-agent-step",
        data: {
          parentToolCallId: "c1",
          kind: "tool",
          state: "started",
          toolCallId: "call_inner",
          toolName: "run_control_tests_on_step",
        },
      },
    ];

    expect(buildTrace(parts)[0]?.groups[0]?.phase).toBe("c1");
  });

  it("names the phase the trace's own group names", () => {
    const parts: MessagePart[] = [
      {
        type: "data-sub-agent-call",
        data: { toolCallId: "c1", phase: "verification", state: "started" },
      },
      {
        type: "data-sub-agent-step",
        data: {
          parentToolCallId: "c1",
          kind: "tool",
          state: "started",
          toolCallId: "call_inner",
          toolName: "run_control_tests_on_step",
        },
      },
    ];

    expect(runningPhase(parts)).toBe(buildTrace(parts)[0]?.groups[0]?.phase);
  });
});
