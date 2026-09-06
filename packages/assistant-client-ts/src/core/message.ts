export type MessageRole = "system" | "user" | "assistant";

export type StreamState = "streaming" | "done";

export interface TextPart {
  type: "text";
  text: string;
  state: StreamState;
}

export interface ReasoningPart {
  type: "reasoning";
  text: string;
  state: StreamState;
}

export interface StepStartPart {
  type: "step-start";
}

export interface FilePart {
  type: "file";
  mediaType: string;
  url: string;
  filename?: string;
}

export interface SourceUrlPart {
  type: "source-url";
  sourceId: string;
  url: string;
  title?: string;
}

export interface SourceDocumentPart {
  type: "source-document";
  sourceId: string;
  mediaType: string;
  title: string;
  filename?: string;
}

export interface DataPart {
  type: `data-${string}`;
  id?: string;
  data: unknown;
}

/** How a tool's own one-line summary reads. Section 6.3. */
export type ToolSummaryStatus = "ok" | "empty" | "warn";

/** What every state of a call shares, including the line the tool wrote. */
export interface ToolPartIdentity {
  type: `tool-${string}`;
  toolCallId: string;
  summary?: string;
  summaryStatus?: ToolSummaryStatus;
}

/** The call's state, as section 9 walks it. */
export type ToolPart = ToolPartIdentity &
  (
    | { state: "input-streaming"; input: unknown; output?: never; errorText?: never }
    | { state: "input-available"; input: unknown; output?: never; errorText?: never }
    | {
        state: "approval-requested";
        input: unknown;
        output?: never;
        errorText?: never;
        approval: { id: string };
      }
    | { state: "output-available"; input: unknown; output: unknown; errorText?: never }
    | { state: "output-error"; input: unknown; output?: never; errorText: string }
    | {
        state: "output-denied";
        input: unknown;
        output?: never;
        errorText?: never;
        approval: { id: string; approved: false };
      }
  );

/** Report whether a part is a tool call, so a reader may address its call id. */
export function isToolPart(part: MessagePart): part is ToolPart {
  return part.type.startsWith("tool-");
}

/** Report whether a part is a data part, whoever registered its kind. */
export function isDataPart(part: MessagePart): part is DataPart {
  return part.type.startsWith("data-");
}

export type MessagePart =
  | TextPart
  | ReasoningPart
  | StepStartPart
  | FilePart
  | SourceUrlPart
  | SourceDocumentPart
  | DataPart
  | ToolPart;

/** One assistant message, plus the turn facts section 6 says a client needs. */
export interface AssistantMessage {
  id: string;
  role: MessageRole;
  parts: MessagePart[];
  metadata?: Record<string, unknown>;
  errors: string[];
  aborted: boolean;
  finishReason?: string;
}

export interface PromptMessage {
  id: string;
  role: MessageRole;
  parts: MessagePart[];
  metadata?: Record<string, unknown>;
}

export type ThreadMessage = AssistantMessage | PromptMessage;
