import {
  type ProtocolChunk,
  isDataChunk,
  readBoolean,
  readRecord,
  readString,
  readValue,
} from "./chunks.ts";
import {
  type AssistantMessage,
  type DataPart,
  type MessagePart,
  type ReasoningPart,
  type StreamState,
  type TextPart,
} from "./message.ts";
import {
  type ToolTracker,
  applyToolChunk,
  applyToolSummary,
  toolChunkKinds,
} from "./reduceTool.ts";

/** Every chunk kind the reducer answers to. Section 5.1 is the whole list. */
export const HANDLED_CHUNK_KINDS: ReadonlySet<string> = new Set([
  "start",
  "start-step",
  "finish-step",
  "text-start",
  "text-delta",
  "text-end",
  "reasoning-start",
  "reasoning-delta",
  "reasoning-end",
  ...toolChunkKinds,
  "file",
  "source-url",
  "source-document",
  "message-metadata",
  "error",
  "abort",
  "finish",
  "done",
]);

interface TurnAccumulator {
  id: string;
  parts: MessagePart[];
  metadata: Record<string, unknown>;
  hasMetadata: boolean;
  errors: string[];
  aborted: boolean;
  finishReason: string | undefined;
  text: Map<string, number>;
  reasoning: Map<string, number>;
  data: Map<string, Map<string, number>>;
  tools: ToolTracker;
}

function emptyAccumulator(): TurnAccumulator {
  return {
    id: "",
    parts: [],
    metadata: {},
    hasMetadata: false,
    errors: [],
    aborted: false,
    finishReason: undefined,
    text: new Map(),
    reasoning: new Map(),
    data: new Map(),
    tools: new Map(),
  };
}

function mergeMetadata(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  const metadata = readRecord(chunk, "messageMetadata");
  if (metadata === undefined) return;
  Object.assign(turn.metadata, metadata);
  turn.hasMetadata = true;
}

function openStreamPart(
  turn: TurnAccumulator,
  index: Map<string, number>,
  chunk: ProtocolChunk,
  type: "text" | "reasoning",
): void {
  const id = readString(chunk, "id");
  if (id === undefined) return;
  index.set(id, turn.parts.length);
  turn.parts.push({ type, text: "", state: "streaming" });
}

function streamPartAt(
  turn: TurnAccumulator,
  index: Map<string, number>,
  chunk: ProtocolChunk,
): TextPart | ReasoningPart | undefined {
  const id = readString(chunk, "id");
  if (id === undefined) return undefined;
  const at = index.get(id);
  if (at === undefined) return undefined;
  const part = turn.parts[at];
  if (part === undefined) return undefined;
  return part.type === "text" || part.type === "reasoning" ? part : undefined;
}

function appendDelta(
  turn: TurnAccumulator,
  index: Map<string, number>,
  chunk: ProtocolChunk,
): void {
  const part = streamPartAt(turn, index, chunk);
  const delta = readString(chunk, "delta");
  if (part === undefined || delta === undefined) return;
  part.text += delta;
}

function closeStreamPart(
  turn: TurnAccumulator,
  index: Map<string, number>,
  chunk: ProtocolChunk,
): void {
  const part = streamPartAt(turn, index, chunk);
  if (part === undefined) return;
  const state: StreamState = "done";
  part.state = state;
}

function applyDataChunk(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  if (readBoolean(chunk, "transient")) return;
  const type = chunk.type as `data-${string}`;
  const data = readValue(chunk, "data");
  const id = readString(chunk, "id");
  if (id === undefined) {
    turn.parts.push({ type, data });
    return;
  }
  const byId = turn.data.get(type) ?? new Map<string, number>();
  turn.data.set(type, byId);
  const at = byId.get(id);
  if (at === undefined) {
    byId.set(id, turn.parts.length);
    turn.parts.push({ type, id, data });
    return;
  }
  const part: DataPart = { type, id, data };
  turn.parts[at] = part;
}

function appendFile(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  const url = readString(chunk, "url");
  const mediaType = readString(chunk, "mediaType");
  if (url === undefined || mediaType === undefined) return;
  const filename = readString(chunk, "filename");
  turn.parts.push(
    filename === undefined
      ? { type: "file", url, mediaType }
      : { type: "file", url, mediaType, filename },
  );
}

function appendSourceUrl(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  const sourceId = readString(chunk, "sourceId");
  const url = readString(chunk, "url");
  if (sourceId === undefined || url === undefined) return;
  const title = readString(chunk, "title");
  turn.parts.push(
    title === undefined
      ? { type: "source-url", sourceId, url }
      : { type: "source-url", sourceId, url, title },
  );
}

function appendSourceDocument(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  const sourceId = readString(chunk, "sourceId");
  const mediaType = readString(chunk, "mediaType");
  const title = readString(chunk, "title");
  if (sourceId === undefined || mediaType === undefined || title === undefined) return;
  const filename = readString(chunk, "filename");
  turn.parts.push(
    filename === undefined
      ? { type: "source-document", sourceId, mediaType, title }
      : { type: "source-document", sourceId, mediaType, title, filename },
  );
}

function applyChunk(turn: TurnAccumulator, chunk: ProtocolChunk): void {
  if (isDataChunk(chunk)) {
    if (applyToolSummary(turn.tools, turn.parts, chunk)) return;
    applyDataChunk(turn, chunk);
    return;
  }
  if (applyToolChunk(turn.tools, turn.parts, chunk)) return;
  switch (chunk.type) {
    case "start":
      turn.id = readString(chunk, "messageId") ?? turn.id;
      mergeMetadata(turn, chunk);
      return;
    case "start-step":
      turn.parts.push({ type: "step-start" });
      return;
    case "text-start":
      openStreamPart(turn, turn.text, chunk, "text");
      return;
    case "text-delta":
      appendDelta(turn, turn.text, chunk);
      return;
    case "text-end":
      closeStreamPart(turn, turn.text, chunk);
      return;
    case "reasoning-start":
      openStreamPart(turn, turn.reasoning, chunk, "reasoning");
      return;
    case "reasoning-delta":
      appendDelta(turn, turn.reasoning, chunk);
      return;
    case "reasoning-end":
      closeStreamPart(turn, turn.reasoning, chunk);
      return;
    case "file":
      appendFile(turn, chunk);
      return;
    case "source-url":
      appendSourceUrl(turn, chunk);
      return;
    case "source-document":
      appendSourceDocument(turn, chunk);
      return;
    case "message-metadata":
      mergeMetadata(turn, chunk);
      return;
    case "error": {
      const errorText = readString(chunk, "errorText");
      if (errorText !== undefined) turn.errors.push(errorText);
      return;
    }
    case "abort":
      turn.aborted = true;
      return;
    case "finish":
      turn.finishReason = readString(chunk, "finishReason") ?? turn.finishReason;
      mergeMetadata(turn, chunk);
      return;
    default:
      return;
  }
}

function finish(turn: TurnAccumulator): AssistantMessage {
  const message: AssistantMessage = {
    id: turn.id,
    role: "assistant",
    parts: turn.parts,
    errors: turn.errors,
    aborted: turn.aborted,
  };
  if (turn.hasMetadata) message.metadata = turn.metadata;
  if (turn.finishReason !== undefined) message.finishReason = turn.finishReason;
  return message;
}

/** Reduce one turn's chunks into the assistant message section 9 describes. */
export function reduceTurn(chunks: readonly ProtocolChunk[]): AssistantMessage {
  const turn = emptyAccumulator();
  for (const chunk of chunks) applyChunk(turn, chunk);
  return finish(turn);
}
