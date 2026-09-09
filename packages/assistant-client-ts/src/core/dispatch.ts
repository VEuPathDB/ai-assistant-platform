import { asRecord, fieldString } from "./chunks.ts";
import type { PartLike } from "./message.ts";

/** The kind that announces one sub-agent dispatch. Section 5.2. */
export const SUB_AGENT_CALL = "data-sub-agent-call";

/** One dispatch payload: the call it names, the phase it ran and its state. */
export interface Dispatch {
  key: string;
  /** The phase the dispatch ran. An empty phase names none. */
  phase: string | undefined;
  state: string | undefined;
  data: Record<string, unknown>;
}

export function readDispatch(part: PartLike): Dispatch | undefined {
  const data = asRecord(part.data);
  if (data === undefined) return undefined;
  const key = fieldString(data, "toolCallId");
  if (key === undefined) return undefined;
  const phase = fieldString(data, "phase");
  const state = fieldString(data, "state");
  return { key, phase: phase === "" ? undefined : phase, state, data };
}

/**
 * The phase of the dispatch a turn still has open, or null when none is. It
 * reads the payload the trace reads, so a status line and a trace group can
 * never name different phases.
 */
export function runningPhase(parts: readonly PartLike[]): string | null {
  const open = new Map<string, string>();
  for (const part of parts) {
    if (part.type !== SUB_AGENT_CALL) continue;
    const call = readDispatch(part);
    if (call?.phase === undefined || call.state === undefined) continue;
    if (call.state === "started") open.set(call.key, call.phase);
    else open.delete(call.key);
  }
  return [...open.values()].at(-1) ?? null;
}
