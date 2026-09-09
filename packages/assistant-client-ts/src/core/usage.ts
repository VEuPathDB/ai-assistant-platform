import { asRecord, fieldNumber, fieldString } from "./chunks.ts";
import type { MessageLike, PartLike } from "./message.ts";

const LEAD_USAGE = "data-lead-usage";
const SUB_AGENT_CALL = "data-sub-agent-call";
const ASSISTANT = "assistant";

/** What one agent spent: cumulative tokens, and cost in US dollars. */
export interface Usage {
  tokens: number;
  costUsd: number;
}

export interface TurnUsage {
  /** The lead agent alone, or null when the turn reports no usage of its own. */
  lead: Usage | null;
  /** The model the lead ran, as the wire spells it. */
  modelId: string | null;
  subAgents: Usage;
  total: Usage;
}

export interface ThreadUsage {
  lead: Usage;
  subAgents: Usage;
  total: Usage;
}

/**
 * The counts a usage payload states. `tokens` is a number and `costUsd` is a
 * decimal string, so a field of another type reads as nothing spent.
 */
function usageOf(data: Record<string, unknown>): Usage {
  const cost = Number(fieldString(data, "costUsd") ?? "");
  return {
    tokens: fieldNumber(data, "tokens") ?? 0,
    costUsd: Number.isFinite(cost) ? cost : 0,
  };
}

function add(total: Usage, more: Usage): Usage {
  return { tokens: total.tokens + more.tokens, costUsd: total.costUsd + more.costUsd };
}

function zero(): Usage {
  return { tokens: 0, costUsd: 0 };
}

/**
 * What one turn spent: the lead's own usage, and every sub-agent it dispatched.
 * The lead part reconciles on its id, so the last one read is the turn's.
 */
export function turnUsage(parts: readonly PartLike[]): TurnUsage {
  let lead: Usage | null = null;
  let modelId: string | null = null;
  let subAgents = zero();
  for (const part of parts) {
    const data = asRecord(part.data);
    if (data === undefined) continue;
    if (part.type === LEAD_USAGE) {
      lead = usageOf(data);
      modelId = fieldString(data, "modelId") ?? null;
    } else if (part.type === SUB_AGENT_CALL) {
      subAgents = add(subAgents, usageOf(data));
    }
  }
  return { lead, modelId, subAgents, total: add(lead ?? zero(), subAgents) };
}

/** What a whole thread spent, summed over the turns the assistant answered. */
export function threadUsage(messages: readonly MessageLike[]): ThreadUsage {
  let lead = zero();
  let subAgents = zero();
  for (const message of messages) {
    if (message.role !== ASSISTANT) continue;
    const turn = turnUsage(message.parts);
    if (turn.lead !== null) lead = add(lead, turn.lead);
    subAgents = add(subAgents, turn.subAgents);
  }
  return { lead, subAgents, total: add(lead, subAgents) };
}
