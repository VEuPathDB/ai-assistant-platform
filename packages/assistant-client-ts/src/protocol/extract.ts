interface CapturedExample {
  kind: string;
  json: string;
}

interface CapturedRequest {
  coreFields: string[];
  extensionFields: string[];
  examples: CapturedExample[];
}

interface CapturedProtocol {
  version: string;
  chunkKinds: string[];
  dataPartKinds: string[];
  envelopeKinds: string[];
  finishReasons: string[];
  taskLifecycle: string[];
  request: CapturedRequest;
  examples: CapturedExample[];
}

class ProtocolExtractionError extends Error {}

function section(markdown: string, name: string): string {
  const begin = `<!-- ${name}:begin -->`;
  const end = `<!-- ${name}:end -->`;
  const from = markdown.indexOf(begin);
  const to = markdown.indexOf(end);
  if (from < 0 || to < from) {
    throw new ProtocolExtractionError(`PROTOCOL.md has no ${name} section`);
  }
  return markdown.slice(from + begin.length, to);
}

function tableRowKeys(table: string): string[] {
  const keys: string[] = [];
  for (const line of table.split("\n")) {
    const match = /^\|\s*`([^`]+)`\s*\|/.exec(line.trim());
    if (match?.[1] !== undefined) keys.push(match[1]);
  }
  return keys;
}

function tableKeys(table: string, label: string): string[] {
  const keys = tableRowKeys(table);
  if (keys.length === 0) {
    throw new ProtocolExtractionError(`PROTOCOL.md ${label} table names nothing`);
  }
  return keys;
}

function extractVersion(markdown: string): string {
  const match = /^\*\*Version (\d+\.\d+\.\d+)\.\*\*/m.exec(markdown);
  if (match?.[1] === undefined) {
    throw new ProtocolExtractionError("PROTOCOL.md declares no version");
  }
  return match[1];
}

const FINISH_REASON_HEADING = "`finishReason` reports how the turn ended:";

function extractFinishReasons(markdown: string): string[] {
  const at = markdown.indexOf(FINISH_REASON_HEADING);
  if (at < 0) {
    throw new ProtocolExtractionError("PROTOCOL.md states no finishReason table");
  }
  const rest = markdown.slice(at + FINISH_REASON_HEADING.length);
  const stop = rest.indexOf("\n\n", rest.indexOf("|"));
  return tableKeys(stop < 0 ? rest : rest.slice(0, stop), "finishReason");
}

const EXAMPLE_PATTERN = /####\s+`([^`]+)`\s*\n+```json\n([\s\S]*?)\n```/g;

function extractExamples(markdown: string, name: string): CapturedExample[] {
  const body = section(markdown, name);
  const examples: CapturedExample[] = [];
  for (const match of body.matchAll(EXAMPLE_PATTERN)) {
    const kind = match[1];
    const json = match[2];
    if (kind === undefined || json === undefined) continue;
    JSON.parse(json);
    examples.push({ kind, json });
  }
  if (examples.length === 0) {
    throw new ProtocolExtractionError(`PROTOCOL.md ${name} captures nothing`);
  }
  return examples;
}

function extractRequest(markdown: string): CapturedRequest {
  return {
    coreFields: tableKeys(section(markdown, "request_core"), "request core field"),
    // The extension table is the one table a document may leave empty: the
    // fields it would name belong to a host, not to this protocol.
    extensionFields: tableRowKeys(section(markdown, "request_extensions")),
    examples: extractExamples(markdown, "request_examples"),
  };
}

/** Read the wire contract out of the document that defines it. */
export function extractProtocol(markdown: string): CapturedProtocol {
  return {
    version: extractVersion(markdown),
    chunkKinds: tableKeys(section(markdown, "chunks"), "chunk"),
    dataPartKinds: tableKeys(section(markdown, "data_parts"), "data part"),
    envelopeKinds: tableKeys(section(markdown, "envelopes"), "envelope"),
    finishReasons: extractFinishReasons(markdown),
    taskLifecycle: tableKeys(section(markdown, "task_lifecycle"), "task lifecycle"),
    request: extractRequest(markdown),
    examples: extractExamples(markdown, "examples"),
  };
}
