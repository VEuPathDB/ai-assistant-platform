import captured from "../protocol/captured.json" with { type: "json" };

/** A chunk as it arrives: a discriminating `type` and fields a client may not know. */
export interface ProtocolChunk {
  readonly type: string;
  readonly [field: string]: unknown;
}

const DATA_PART_PREFIX = "data-";

export function isDataChunk(chunk: ProtocolChunk): boolean {
  return chunk.type.startsWith(DATA_PART_PREFIX);
}

const CHUNK_KINDS: ReadonlySet<string> = new Set(captured.chunkKinds);

/**
 * Report whether this protocol version defines the kind. A client ignores what
 * it does not recognise, which is what makes the additive rule safe.
 */
export function isKnownChunkKind(type: string): boolean {
  return type.startsWith(DATA_PART_PREFIX) || CHUNK_KINDS.has(type);
}

export function readString(chunk: ProtocolChunk, field: string): string | undefined {
  const value = chunk[field];
  return typeof value === "string" ? value : undefined;
}

export function readBoolean(chunk: ProtocolChunk, field: string): boolean {
  return chunk[field] === true;
}

/** Read a value the protocol defines as an object. */
export function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

export function readRecord(
  chunk: ProtocolChunk,
  field: string,
): Record<string, unknown> | undefined {
  return asRecord(chunk[field]);
}

export function fieldString(
  record: Record<string, unknown>,
  field: string,
): string | undefined {
  const value = record[field];
  return typeof value === "string" ? value : undefined;
}

export function fieldNumber(
  record: Record<string, unknown>,
  field: string,
): number | undefined {
  const value = record[field];
  return typeof value === "number" ? value : undefined;
}

/** Read a value the protocol defines as free-form. */
export function readValue(chunk: ProtocolChunk, field: string): unknown {
  return chunk[field];
}

export function asChunk(value: unknown): ProtocolChunk | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  return typeof record["type"] === "string" ? (record as ProtocolChunk) : undefined;
}

/**
 * Parse a frame payload into a chunk. Throws when the payload is not JSON.
 * The caller drops the terminator first: its payload is a literal, not a chunk.
 */
export function parseChunk(payload: string): ProtocolChunk | undefined {
  return asChunk(JSON.parse(payload));
}
