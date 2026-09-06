import { asRecord, fieldString } from "./chunks.ts";

export interface SubAgentStepPayload {
  parentToolCallId: string;
  kind: "tool" | "reasoning" | "text";
  state: "started" | "completed" | "failed" | "denied";
  toolCallId?: string | null;
  toolName?: string | null;
  args?: Record<string, unknown> | null;
  resultSummary?: string | null;
  text?: string | null;
}

export type SubAgentItem =
  | {
      type: "tool";
      key: string;
      toolName: string;
      args: Record<string, unknown> | null;
      result: string | null;
      state: SubAgentStepPayload["state"];
    }
  | { type: "reasoning" | "text"; key: string; text: string };

const KINDS: readonly SubAgentStepPayload["kind"][] = ["tool", "reasoning", "text"];
const STATES: readonly SubAgentStepPayload["state"][] = [
  "started",
  "completed",
  "failed",
  "denied",
];

/** Read one step payload off a data part, or nothing when it is malformed. */
export function readSubAgentStep(data: unknown): SubAgentStepPayload | undefined {
  const record = asRecord(data);
  if (record === undefined) return undefined;
  const parent = fieldString(record, "parentToolCallId");
  const kind = KINDS.find((known) => known === record["kind"]);
  const state = STATES.find((known) => known === record["state"]);
  if (parent === undefined || kind === undefined || state === undefined) {
    return undefined;
  }
  return {
    parentToolCallId: parent,
    kind,
    state,
    toolCallId: fieldString(record, "toolCallId") ?? null,
    toolName: fieldString(record, "toolName") ?? null,
    args: asRecord(record["args"]) ?? null,
    resultSummary: fieldString(record, "resultSummary") ?? null,
    text: fieldString(record, "text") ?? null,
  };
}

/**
 * Collapse a sub-agent's raw step stream into render-ready items. A tool call
 * arrives as a `started` step carrying `args` and a later terminal step
 * carrying `resultSummary`; both share a `toolCallId` and are one item.
 */
export function mergeSubAgentSteps(
  steps: readonly SubAgentStepPayload[],
): SubAgentItem[] {
  const items: SubAgentItem[] = [];
  const toolIndex = new Map<string, number>();
  steps.forEach((step, i) => {
    if (step.kind !== "tool") {
      items.push({ type: step.kind, key: `${step.kind}-${i}`, text: step.text ?? "" });
      return;
    }
    const id = step.toolCallId ?? `${step.toolName ?? "tool"}-${i}`;
    const at = toolIndex.get(id);
    if (at === undefined) {
      items.push({
        type: "tool",
        key: id,
        toolName: step.toolName ?? "unknown",
        args: step.args ?? null,
        result: step.resultSummary ?? null,
        state: step.state,
      });
      toolIndex.set(id, items.length - 1);
      return;
    }
    const existing = items[at];
    if (existing?.type !== "tool") return;
    if (step.args !== undefined && step.args !== null) existing.args = step.args;
    const result = step.resultSummary;
    if (result !== undefined && result !== null && result !== "") {
      existing.result = result;
    }
    existing.state = step.state;
  });
  return items;
}
