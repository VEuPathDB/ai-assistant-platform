import { asRecord, fieldNumber, fieldString } from "./chunks.ts";
import {
  type DataPart,
  type MessagePart,
  type ToolPart,
  type ToolSummaryStatus,
  isDataPart,
  isToolPart,
} from "./message.ts";
import { TOOL_SUMMARY_KIND } from "./reduceTool.ts";
import {
  type SubAgentStepPayload,
  mergeSubAgentSteps,
  readSubAgentStep,
} from "./subAgentSteps.ts";

export type TraceRowStatus =
  | "running"
  | "ok"
  | "empty"
  | "warn"
  | "error"
  | "denied"
  | "awaiting-approval"
  | "stopped";

export type TraceGroupState =
  "started" | "completed" | "failed" | "cancelled" | "superseded";

export interface TraceRow {
  key: string;
  toolCallId: string;
  toolName: string;
  summary: string | null;
  status: TraceRowStatus;
  input: unknown;
  output: unknown;
  errorText: string | null;
}

export interface TraceGroup {
  key: string;
  phase: string;
  rows: TraceRow[];
  tokens: number;
  costUsd: string;
  state: TraceGroupState;
}

export interface Trace {
  groups: TraceGroup[];
  figures: DataPart[];
  rowCount: number;
  running: boolean;
}

export interface BuildTraceOptions {
  renderingKinds?: ReadonlySet<string>;
  turnEnded?: boolean;
}

const LEAD = "lead";
const NO_KINDS: ReadonlySet<string> = new Set();
const STATUSES: readonly ToolSummaryStatus[] = ["ok", "empty", "warn"];
const WIRE_STATES: readonly TraceGroupState[] = ["started", "completed", "failed"];
const TURN_STOPPED = "data-turn-stopped";
const TURN_FAILED = "data-turn-failed";
const STEP_STATUS: Record<SubAgentStepPayload["state"], TraceRowStatus> = {
  started: "running",
  completed: "ok",
  failed: "error",
  denied: "denied",
};

interface Line {
  summary: string;
  status: ToolSummaryStatus;
}

interface GroupBuild {
  key: string;
  phase: string;
  rows: TraceRow[];
  steps: SubAgentStepPayload[];
  tokens: number;
  costUsd: string;
  state: TraceGroupState;
  fromSteps: boolean;
}

interface RunBuild {
  groups: GroupBuild[];
  figures: DataPart[];
}

interface Walk {
  traces: Trace[];
  open: RunBuild | null;
  group: GroupBuild | null;
  dispatches: TraceGroup[];
  lines: Map<string, Line>;
  kinds: ReadonlySet<string>;
}

function rowStatus(part: ToolPart): TraceRowStatus {
  switch (part.state) {
    case "input-streaming":
    case "input-available":
      return "running";
    case "approval-requested":
      return "awaiting-approval";
    case "output-error":
      return "error";
    case "output-denied":
      return "denied";
    case "output-available":
      return part.summaryStatus ?? "ok";
  }
}

function toolRow(part: ToolPart): TraceRow {
  return {
    key: part.toolCallId,
    toolCallId: part.toolCallId,
    toolName: part.type.slice("tool-".length),
    summary: part.summary ?? null,
    status: rowStatus(part),
    input: part.input,
    output: part.state === "output-available" ? part.output : null,
    errorText: part.state === "output-error" ? part.errorText : null,
  };
}

function stepRows(steps: readonly SubAgentStepPayload[]): TraceRow[] {
  const rows: TraceRow[] = [];
  for (const item of mergeSubAgentSteps(steps)) {
    if (item.type !== "tool") continue;
    const failed = item.state === "failed";
    rows.push({
      key: item.key,
      toolCallId: item.key,
      toolName: item.toolName,
      summary: failed ? null : item.result,
      status: STEP_STATUS[item.state],
      input: item.args,
      output: null,
      errorText: failed ? item.result : null,
    });
  }
  return rows;
}

function finalize(group: GroupBuild): TraceGroup {
  return {
    key: group.key,
    phase: group.phase,
    rows: group.fromSteps ? stepRows(group.steps) : group.rows,
    tokens: group.tokens,
    costUsd: group.costUsd,
    state: group.state,
  };
}

function closeRun(walk: Walk): void {
  const open = walk.open;
  walk.open = null;
  walk.group = null;
  if (open === null) return;
  const built = open.groups.map((build) => ({
    group: finalize(build),
    dispatch: build.fromSteps,
  }));
  const groups = built.map((each) => each.group);
  const rowCount = groups.reduce((total, group) => total + group.rows.length, 0);
  if (rowCount === 0 && open.figures.length === 0) return;
  for (const each of built) if (each.dispatch) walk.dispatches.push(each.group);
  walk.traces.push({ groups, figures: open.figures, rowCount, running: false });
}

function ensureRun(walk: Walk): RunBuild {
  const open = walk.open ?? { groups: [], figures: [] };
  walk.open = open;
  return open;
}

function ensureGroup(walk: Walk, key: string, phase: string): GroupBuild {
  const run = ensureRun(walk);
  const held = walk.group;
  if (held !== null && held.key === key) return held;
  const group: GroupBuild = {
    key,
    phase,
    rows: [],
    steps: [],
    tokens: 0,
    costUsd: "0",
    state: "started",
    fromSteps: false,
  };
  run.groups.push(group);
  walk.group = group;
  return group;
}

function openDispatch(walk: Walk, part: DataPart): void {
  const data = asRecord(part.data);
  if (data === undefined) return;
  const key = fieldString(data, "toolCallId");
  if (key === undefined) return;
  const phase = fieldString(data, "phase");
  const group = ensureGroup(walk, key, phase ?? key);
  group.fromSteps = true;
  if (phase !== undefined) group.phase = phase;
  group.state = WIRE_STATES.find((known) => known === data["state"]) ?? group.state;
  group.tokens = fieldNumber(data, "tokens") ?? group.tokens;
  group.costUsd = fieldString(data, "costUsd") ?? group.costUsd;
}

function pushStep(walk: Walk, part: DataPart): void {
  const payload = readSubAgentStep(part.data);
  const run = walk.open;
  if (payload === undefined || run === null) return;
  const group = run.groups.find((each) => each.key === payload.parentToolCallId);
  if (group === undefined) return;
  group.steps.push(payload);
}

function recordLine(walk: Walk, part: DataPart): void {
  const data = asRecord(part.data);
  if (data === undefined) return;
  const toolCallId = fieldString(data, "toolCallId");
  const summary = fieldString(data, "summary");
  if (toolCallId === undefined || summary === undefined) return;
  const raw = fieldString(data, "status");
  const status = STATUSES.find((known) => known === raw) ?? "ok";
  walk.lines.set(toolCallId, { summary, status });
}

function visitData(walk: Walk, part: DataPart): void {
  if (part.type === TOOL_SUMMARY_KIND) return recordLine(walk, part);
  if (part.type === "data-sub-agent-call") return openDispatch(walk, part);
  if (part.type === "data-sub-agent-step") return pushStep(walk, part);
  if (walk.kinds.has(part.type)) ensureRun(walk).figures.push(part);
}

function visit(walk: Walk, part: MessagePart): void {
  if (part.type === "text") {
    if (part.text.trim() !== "") closeRun(walk);
    return;
  }
  if (part.type === "reasoning" || part.type === "step-start") return;
  if (isToolPart(part)) {
    ensureGroup(walk, LEAD, LEAD).rows.push(toolRow(part));
    return;
  }
  if (isDataPart(part)) visitData(walk, part);
}

function applyLines(walk: Walk): void {
  for (const trace of walk.traces) {
    for (const group of trace.groups) {
      for (const row of group.rows) {
        const line = walk.lines.get(row.toolCallId);
        if (line === undefined) continue;
        row.summary = line.summary;
        if (row.status === "ok") row.status = line.status;
      }
      trace.running ||= group.rows.some(
        (row) => row.status === "running" || row.status === "awaiting-approval",
      );
    }
  }
}

/** How a turn that ended reads a dispatch it never resolved. */
function closingState(
  parts: readonly MessagePart[],
  turnEnded: boolean,
): TraceGroupState | null {
  if (parts.some((part) => part.type === TURN_STOPPED)) return "cancelled";
  if (parts.some((part) => part.type === TURN_FAILED)) return "failed";
  return turnEnded ? "superseded" : null;
}

function closeDispatches(walk: Walk, state: TraceGroupState | null): void {
  if (state === null) return;
  for (const group of walk.dispatches) {
    if (group.state !== "started") continue;
    group.state = state;
    if (state === "superseded") continue;
    for (const row of group.rows) {
      if (row.status === "running") row.status = "stopped";
    }
  }
}

/**
 * Group a message's parts into the runs a reader sees: one trace per stretch of
 * work between the prose that frames it.
 */
export function buildTrace(
  parts: readonly MessagePart[],
  options?: BuildTraceOptions,
): Trace[] {
  const walk: Walk = {
    traces: [],
    open: null,
    group: null,
    dispatches: [],
    lines: new Map(),
    kinds: options?.renderingKinds ?? NO_KINDS,
  };
  for (const part of parts) visit(walk, part);
  closeRun(walk);
  closeDispatches(walk, closingState(parts, options?.turnEnded ?? false));
  applyLines(walk);
  return walk.traces;
}
