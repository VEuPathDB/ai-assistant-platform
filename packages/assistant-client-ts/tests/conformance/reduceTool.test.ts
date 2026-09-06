import { describe, expect, it } from "vitest";

import { reduceTurn } from "../../src/core/reduce.ts";
import { type ProtocolChunk } from "../../src/core/chunks.ts";

function turn(...chunks: ProtocolChunk[]): ProtocolChunk[] {
  return chunks;
}

describe("section 9, tool parts", () => {
  it("walks one call from input-streaming to output-available", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-start", toolCallId: "call_add", toolName: "add" },
        { type: "tool-input-delta", toolCallId: "call_add", inputTextDelta: '{"a":2,' },
        { type: "tool-input-delta", toolCallId: "call_add", inputTextDelta: '"b":3}' },
        {
          type: "tool-input-available",
          toolCallId: "call_add",
          toolName: "add",
          input: { a: 2, b: 3 },
        },
        { type: "tool-output-available", toolCallId: "call_add", output: 5 },
      ),
    );

    expect(message.parts).toEqual([
      {
        type: "tool-add",
        toolCallId: "call_add",
        state: "output-available",
        input: { a: 2, b: 3 },
        output: 5,
      },
    ]);
  });

  it("holds the raw input text while the call streams", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-start", toolCallId: "c", toolName: "add" },
        { type: "tool-input-delta", toolCallId: "c", inputTextDelta: '{"a":' },
      ),
    );

    expect(message.parts).toEqual([
      { type: "tool-add", toolCallId: "c", state: "input-streaming", input: '{"a":' },
    ]);
  });

  it("patches the one part rather than appending a second", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-start", toolCallId: "c", toolName: "wipe" },
        { type: "tool-input-available", toolCallId: "c", toolName: "wipe", input: {} },
        {
          type: "tool-output-error",
          toolCallId: "c",
          errorText: "Tool execution was interrupted by an error.",
        },
      ),
    );

    expect(message.parts).toHaveLength(1);
    expect(message.parts[0]).toEqual({
      type: "tool-wipe",
      toolCallId: "c",
      state: "output-error",
      input: {},
      errorText: "Tool execution was interrupted by an error.",
    });
  });

  it("opens a part on tool-input-available alone", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        {
          type: "tool-input-available",
          toolCallId: "c",
          toolName: "add",
          input: { a: 1 },
        },
      ),
    );

    expect(message.parts).toEqual([
      { type: "tool-add", toolCallId: "c", state: "input-available", input: { a: 1 } },
    ]);
  });

  it("moves a call to approval-requested and carries the approval id", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-available", toolCallId: "c", toolName: "wipe", input: {} },
        { type: "tool-approval-request", toolCallId: "c", approvalId: "ap1" },
      ),
    );

    expect(message.parts).toEqual([
      {
        type: "tool-wipe",
        toolCallId: "c",
        state: "approval-requested",
        input: {},
        approval: { id: "ap1" },
      },
    ]);
  });

  it("moves a refused call to output-denied", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-available", toolCallId: "c", toolName: "wipe", input: {} },
        { type: "tool-approval-request", toolCallId: "c", approvalId: "ap1" },
        { type: "tool-output-denied", toolCallId: "c" },
      ),
    );

    expect(message.parts).toEqual([
      {
        type: "tool-wipe",
        toolCallId: "c",
        state: "output-denied",
        input: {},
        approval: { id: "ap1", approved: false },
      },
    ]);
  });

  it("records an input that could not be parsed", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-input-start", toolCallId: "c", toolName: "add" },
        {
          type: "tool-input-error",
          toolCallId: "c",
          toolName: "add",
          errorText: "bad json",
        },
      ),
    );

    expect(message.parts).toEqual([
      {
        type: "tool-add",
        toolCallId: "c",
        state: "output-error",
        input: undefined,
        errorText: "bad json",
      },
    ]);
  });

  it("ignores an output for a call it does not hold", () => {
    const message = reduceTurn(
      turn(
        { type: "start", messageId: "m1" },
        { type: "tool-output-available", toolCallId: "gone", output: 1 },
      ),
    );

    expect(message.parts).toEqual([]);
  });
});
