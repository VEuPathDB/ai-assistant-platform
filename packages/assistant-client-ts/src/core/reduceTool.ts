import {
  type ProtocolChunk,
  fieldString,
  readRecord,
  readString,
  readValue,
} from "./chunks.ts";
import {
  type MessagePart,
  type ToolPart,
  type ToolPartIdentity,
  type ToolSummaryStatus,
  isToolPart,
} from "./message.ts";

/** The kind section 6.3 defines. It patches a call and appends no part. */
export const TOOL_SUMMARY_KIND = "data-tool-summary";

const TOOL_SUMMARY_STATUSES: readonly ToolSummaryStatus[] = ["ok", "empty", "warn"];

export const toolChunkKinds = [
  "tool-input-start",
  "tool-input-delta",
  "tool-input-available",
  "tool-input-error",
  "tool-approval-request",
  "tool-output-available",
  "tool-output-error",
  "tool-output-denied",
] as const;

const TOOL_CHUNK_KINDS: ReadonlySet<string> = new Set(toolChunkKinds);

interface ToolTrack {
  index: number;
  toolName: string;
  input: unknown;
  inputText: string;
  approvalId: string | undefined;
  summary: string | undefined;
  summaryStatus: ToolSummaryStatus | undefined;
}

export type ToolTracker = Map<string, ToolTrack>;

/**
 * The fields every state of the call shares. The summary rides here so a line
 * written before the output survives the write that carries the output.
 */
function identity(track: ToolTrack, toolCallId: string): ToolPartIdentity {
  const shared: ToolPartIdentity = { type: `tool-${track.toolName}`, toolCallId };
  if (track.summary !== undefined) shared.summary = track.summary;
  if (track.summaryStatus !== undefined) shared.summaryStatus = track.summaryStatus;
  return shared;
}

function openTrack(
  tracker: ToolTracker,
  parts: MessagePart[],
  chunk: ProtocolChunk,
  toolCallId: string,
): ToolTrack | undefined {
  const toolName = readString(chunk, "toolName");
  if (toolName === undefined) return undefined;
  const track: ToolTrack = {
    index: parts.length,
    toolName,
    input: undefined,
    inputText: "",
    approvalId: undefined,
    summary: undefined,
    summaryStatus: undefined,
  };
  tracker.set(toolCallId, track);
  parts.push({
    ...identity(track, toolCallId),
    state: "input-streaming",
    input: undefined,
  });
  return track;
}

function write(parts: MessagePart[], track: ToolTrack, part: ToolPart): void {
  parts[track.index] = part;
}

function applyInputDelta(
  parts: MessagePart[],
  track: ToolTrack,
  chunk: ProtocolChunk,
  toolCallId: string,
): void {
  const delta = readString(chunk, "inputTextDelta");
  if (delta === undefined) return;
  track.inputText += delta;
  track.input = track.inputText;
  write(parts, track, {
    ...identity(track, toolCallId),
    state: "input-streaming",
    input: track.input,
  });
}

function applyApprovalRequest(
  parts: MessagePart[],
  track: ToolTrack,
  chunk: ProtocolChunk,
  toolCallId: string,
): void {
  const approvalId = readString(chunk, "approvalId");
  if (approvalId === undefined) return;
  track.approvalId = approvalId;
  write(parts, track, {
    ...identity(track, toolCallId),
    state: "approval-requested",
    input: track.input,
    approval: { id: approvalId },
  });
}

function applyDenial(parts: MessagePart[], track: ToolTrack, toolCallId: string): void {
  if (track.approvalId === undefined) return;
  write(parts, track, {
    ...identity(track, toolCallId),
    state: "output-denied",
    input: track.input,
    approval: { id: track.approvalId, approved: false },
  });
}

function applyError(
  parts: MessagePart[],
  track: ToolTrack,
  chunk: ProtocolChunk,
  toolCallId: string,
  input: unknown,
): void {
  const errorText = readString(chunk, "errorText");
  if (errorText === undefined) return;
  track.input = input;
  write(parts, track, {
    ...identity(track, toolCallId),
    state: "output-error",
    input,
    errorText,
  });
}

function dispatch(
  tracker: ToolTracker,
  parts: MessagePart[],
  chunk: ProtocolChunk,
  toolCallId: string,
): void {
  const held = tracker.get(toolCallId);
  if (chunk.type === "tool-input-start") {
    if (held === undefined) openTrack(tracker, parts, chunk, toolCallId);
    return;
  }
  if (chunk.type === "tool-input-available") {
    const track = held ?? openTrack(tracker, parts, chunk, toolCallId);
    if (track === undefined) return;
    track.input = readValue(chunk, "input");
    write(parts, track, {
      ...identity(track, toolCallId),
      state: "input-available",
      input: track.input,
    });
    return;
  }
  if (held === undefined) return;
  switch (chunk.type) {
    case "tool-input-delta":
      applyInputDelta(parts, held, chunk, toolCallId);
      return;
    case "tool-input-error":
      applyError(parts, held, chunk, toolCallId, undefined);
      return;
    case "tool-output-error":
      applyError(parts, held, chunk, toolCallId, held.input);
      return;
    case "tool-approval-request":
      applyApprovalRequest(parts, held, chunk, toolCallId);
      return;
    case "tool-output-denied":
      applyDenial(parts, held, toolCallId);
      return;
    case "tool-output-available":
      write(parts, held, {
        ...identity(held, toolCallId),
        state: "output-available",
        input: held.input,
        output: readValue(chunk, "output"),
      });
      return;
    default:
      return;
  }
}

/**
 * Apply a summary chunk. Reports whether the chunk was one.
 *
 * This reducer folds the line onto the call's part; the AI SDK's reducer leaves
 * it beside the part. `buildTrace` reads both shapes, which is what makes the
 * two agree.
 */
export function applyToolSummary(
  tracker: ToolTracker,
  parts: MessagePart[],
  chunk: ProtocolChunk,
): boolean {
  if (chunk.type !== TOOL_SUMMARY_KIND) return false;
  const data = readRecord(chunk, "data");
  if (data === undefined) return true;
  const toolCallId = fieldString(data, "toolCallId");
  const summary = fieldString(data, "summary");
  if (toolCallId === undefined || summary === undefined) return true;
  const track = tracker.get(toolCallId);
  if (track === undefined) return true;
  const raw = fieldString(data, "status");
  track.summary = summary;
  track.summaryStatus = TOOL_SUMMARY_STATUSES.find((known) => known === raw) ?? "ok";
  const part = parts[track.index];
  if (part === undefined || !isToolPart(part)) return true;
  part.summary = track.summary;
  part.summaryStatus = track.summaryStatus;
  return true;
}

/** Apply a tool chunk. Reports whether the chunk was one. */
export function applyToolChunk(
  tracker: ToolTracker,
  parts: MessagePart[],
  chunk: ProtocolChunk,
): boolean {
  if (!TOOL_CHUNK_KINDS.has(chunk.type)) return false;
  const toolCallId = readString(chunk, "toolCallId");
  if (toolCallId !== undefined) dispatch(tracker, parts, chunk, toolCallId);
  return true;
}
