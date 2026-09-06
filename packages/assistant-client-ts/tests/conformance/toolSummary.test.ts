import { describe, expect, it } from "vitest";

import { type ProtocolChunk, isKnownChunkKind } from "../../src/core/chunks.ts";
import { type MessagePart, type ToolPart, isToolPart } from "../../src/core/message.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import { PROTOCOL_VERSION } from "../../src/protocol/version.ts";

const KIND = "data-tool-summary";
const CALL = "call_studies";
const TOOL = "search_eda_studies";
const LINE = "3 studies matched heat shock";

const INPUT = { query: "heat shock", limit: 5 };
const OUTPUT = { studies: 3 };

function lifecycle(): ProtocolChunk[] {
  return [
    { type: "start", messageId: "m1" },
    { type: "tool-input-start", toolCallId: CALL, toolName: TOOL },
    { type: "tool-input-available", toolCallId: CALL, toolName: TOOL, input: INPUT },
    { type: "tool-output-available", toolCallId: CALL, output: OUTPUT },
  ];
}

function summary(line: string, status?: string): ProtocolChunk {
  return {
    type: KIND,
    data:
      status === undefined
        ? { toolCallId: CALL, summary: line }
        : { toolCallId: CALL, summary: line, status },
  };
}

function only(parts: readonly MessagePart[]): ToolPart {
  const part = parts[0];
  if (part === undefined || !isToolPart(part)) {
    throw new Error("the reduced message holds no tool part");
  }
  return part;
}

describe("section 6.3, a tool that says what it did", () => {
  it("sets summary and summaryStatus on the call the chunk names", () => {
    const message = reduceTurn([...lifecycle(), summary(LINE, "ok")]);

    expect(message.parts).toHaveLength(1);
    expect(only(message.parts).summary).toBe(LINE);
    expect(only(message.parts).summaryStatus).toBe("ok");
  });

  it("appends no data part for the summary itself", () => {
    const message = reduceTurn([...lifecycle(), summary(LINE, "ok")]);

    expect(message.parts.filter((part) => part.type === KIND)).toEqual([]);
  });

  it("leaves the call untouched when the summary names another call", () => {
    const message = reduceTurn([
      ...lifecycle(),
      { type: KIND, data: { toolCallId: "call_elsewhere", summary: "not this one" } },
    ]);

    expect(message.parts).toHaveLength(1);
    expect(only(message.parts).summary).toBeUndefined();
    expect(only(message.parts).summaryStatus).toBeUndefined();
  });

  it("keeps the last summary when a call carries two", () => {
    const message = reduceTurn([
      ...lifecycle(),
      summary("no study matched heat shock", "empty"),
      summary(LINE, "ok"),
    ]);

    expect(only(message.parts).summary).toBe(LINE);
    expect(only(message.parts).summaryStatus).toBe("ok");
  });

  it("carries a summary written before the output through to the output state", () => {
    const [start, inputStart, inputAvailable, output] = lifecycle();
    if (
      start === undefined ||
      inputStart === undefined ||
      inputAvailable === undefined ||
      output === undefined
    ) {
      throw new Error("the lifecycle fixture is incomplete");
    }

    const message = reduceTurn([
      start,
      inputStart,
      inputAvailable,
      summary(LINE, "warn"),
      output,
    ]);

    expect(only(message.parts).state).toBe("output-available");
    expect(only(message.parts).summary).toBe(LINE);
    expect(only(message.parts).summaryStatus).toBe("warn");
  });

  it("defaults the status to ok, and reads empty when the chunk says so", () => {
    const plain = reduceTurn([...lifecycle(), summary(LINE)]);
    const empty = reduceTurn([
      ...lifecycle(),
      summary("No study matched dhps", "empty"),
    ]);

    expect(only(plain.parts).summaryStatus).toBe("ok");
    expect(only(empty.parts).summaryStatus).toBe("empty");
  });

  it("ignores a chunk that names no call and one whose status is not a status", () => {
    const nameless = reduceTurn([
      ...lifecycle(),
      { type: KIND, data: { summary: LINE } },
    ]);
    const odd = reduceTurn([...lifecycle(), summary(LINE, "excellent")]);

    expect(only(nameless.parts).summary).toBeUndefined();
    expect(only(odd.parts).summaryStatus).toBe("ok");
  });

  it("names the kind as known and reports a protocol version that carries section 6.3", () => {
    expect(isKnownChunkKind(KIND)).toBe(true);
    const [major, minor] = PROTOCOL_VERSION.split(".").map(Number);
    expect(major).toBe(1);
    expect(minor).toBeGreaterThanOrEqual(4);
  });
});
