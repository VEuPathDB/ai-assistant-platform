import { type ProtocolChunk, asChunk, readRecord, readString } from "./chunks.ts";
import {
  type MessagePart,
  type MessageRole,
  type PromptMessage,
  type ThreadMessage,
} from "./message.ts";
import { reduceTurn } from "./reduce.ts";

/** The kinds section 5.3 writes to the log and never frames onto the wire. */
export const HANDLED_ENVELOPE_KINDS: ReadonlySet<string> = new Set([
  "user-message",
  "system-message",
  "assistant-message",
]);

export interface Snapshot {
  chunks: unknown[];
  cursor: number;
}

const ROLES = ["system", "user", "assistant"] as const;

function isRole(value: unknown): value is MessageRole {
  return ROLES.some((role) => role === value);
}

function envelopeMessage(chunk: ProtocolChunk): PromptMessage | undefined {
  const message = readRecord(chunk, "message");
  if (message === undefined) return undefined;
  const id = message["id"];
  const role = message["role"];
  const parts = message["parts"];
  if (typeof id !== "string" || !isRole(role)) return undefined;
  return {
    id,
    role,
    parts: Array.isArray(parts) ? (parts as MessagePart[]) : [],
  };
}

class ThreadBuilder {
  private readonly messages: ThreadMessage[] = [];
  private readonly taken = new Set<string>();
  private pending: ProtocolChunk[] = [];
  private pendingId: string | undefined;

  /** A thread holds each id once, so a log that repeats one keeps the first. */
  private push(message: ThreadMessage): void {
    if (this.taken.has(message.id)) return;
    this.taken.add(message.id);
    this.messages.push(message);
  }

  flush(): void {
    if (this.pending.length === 0) return;
    this.push(reduceTurn(this.pending));
    this.pending = [];
    this.pendingId = undefined;
  }

  addEnvelope(chunk: ProtocolChunk): void {
    this.flush();
    const message = envelopeMessage(chunk);
    if (message !== undefined) this.push(message);
  }

  addTurnChunk(chunk: ProtocolChunk): void {
    if (chunk.type === "start") {
      const messageId = readString(chunk, "messageId");
      if (messageId !== undefined) {
        if (this.pendingId !== undefined && this.pendingId !== messageId) this.flush();
        this.pendingId = messageId;
      }
    }
    this.pending.push(chunk);
  }

  done(): ThreadMessage[] {
    this.flush();
    return this.messages;
  }
}

/** Rebuild a conversation from the snapshot's chunk array. */
export function reduceSnapshot(chunks: readonly unknown[]): ThreadMessage[] {
  const builder = new ThreadBuilder();
  for (const entry of chunks) {
    const chunk = asChunk(entry);
    if (chunk === undefined) continue;
    if (HANDLED_ENVELOPE_KINDS.has(chunk.type)) builder.addEnvelope(chunk);
    else builder.addTurnChunk(chunk);
  }
  return builder.done();
}
