import {
  isCustomContentUIPart,
  isReasoningFileUIPart,
  isToolUIPart,
  type ToolUIPart,
  type UIMessage,
} from "ai";

import {
  type MessagePart,
  type ToolPart,
  type ToolSummaryStatus,
} from "../core/message.ts";
import { toolSummaryStatuses } from "../core/reduceTool.ts";

type UIPart = UIMessage["parts"][number];

interface Line {
  summary?: string;
  summaryStatus?: ToolSummaryStatus;
}

/**
 * The line a tool wrote about its own call, when the SDK's reducer left it
 * beside the part. A status the protocol does not name is no line at all.
 */
function lineOf(part: ToolUIPart): Line {
  const held: Record<string, unknown> = { ...part };
  const summary = held["summary"];
  if (typeof summary !== "string") return {};
  const raw = held["summaryStatus"];
  if (raw === undefined) return { summary };
  const status = toolSummaryStatuses.find((known) => known === raw);
  return status === undefined ? {} : { summary, summaryStatus: status };
}

function toolPart(part: ToolUIPart): ToolPart {
  const head = { type: part.type, toolCallId: part.toolCallId, ...lineOf(part) };
  switch (part.state) {
    case "input-streaming":
    case "input-available":
      return { ...head, state: part.state, input: part.input };
    case "approval-requested":
      return {
        ...head,
        state: "approval-requested",
        input: part.input,
        approval: { id: part.approval.id },
      };
    case "approval-responded":
      return { ...head, state: "input-available", input: part.input };
    case "output-available":
      return {
        ...head,
        state: "output-available",
        input: part.input,
        output: part.output,
      };
    case "output-error":
      return {
        ...head,
        state: "output-error",
        input: part.input,
        errorText: part.errorText,
      };
    case "output-denied":
      return {
        ...head,
        state: "output-denied",
        input: part.input,
        approval: { id: part.approval.id, approved: false },
      };
  }
}

type ProtocolPart = Exclude<
  UIPart,
  { type: "custom" | "reasoning-file" | "dynamic-tool" }
>;

/** Report whether the protocol's chunk vocabulary names this part's kind. */
function isProtocolPart(part: UIPart): part is ProtocolPart {
  if (isCustomContentUIPart(part) || isReasoningFileUIPart(part)) return false;
  return part.type !== "dynamic-tool";
}

/**
 * Read a message's parts as the protocol shape the core ring walks. The SDK's
 * own reducer leaves a tool's summary beside its call and this one folds it on,
 * so both shapes reach a reader unchanged.
 */
export function toTraceParts(parts: readonly UIPart[]): MessagePart[] {
  const out: MessagePart[] = [];
  for (const part of parts) {
    if (!isProtocolPart(part)) continue;
    if (isToolUIPart(part)) {
      out.push(toolPart(part));
      continue;
    }
    out.push(part);
  }
  return out;
}
