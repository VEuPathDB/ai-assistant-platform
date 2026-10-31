import { describe, expect, it } from "vitest";

import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { reduceSnapshot } from "../../src/core/snapshot.ts";

const MESSAGE = "aaaaaaaa-0000-4000-8000-000000000001";
const CALL = "call_wipe";
const APPROVAL = "approval_wipe";
const INPUT = { target: "everything" };

const PROMPT: ProtocolChunk = {
  type: "user-message",
  message: { id: "u1", role: "user", parts: [] },
};

const ASKED: ProtocolChunk[] = [
  { type: "start", messageId: MESSAGE },
  { type: "tool-input-start", toolCallId: CALL, toolName: "wipe" },
  { type: "tool-input-available", toolCallId: CALL, toolName: "wipe", input: INPUT },
  { type: "tool-approval-request", toolCallId: CALL, approvalId: APPROVAL },
  { type: "finish", finishReason: "other" },
  { type: "done" },
];

function answered(...outcome: ProtocolChunk[]): ProtocolChunk[] {
  return [
    { type: "start", messageId: MESSAGE },
    { type: "tool-input-available", toolCallId: CALL, toolName: "wipe", input: INPUT },
    ...outcome,
    { type: "finish", finishReason: "stop" },
    { type: "done" },
  ];
}

function callOf(chunks: ProtocolChunk[]): unknown {
  const messages = reduceSnapshot(chunks);
  expect(messages.map((message) => message.id)).toEqual(["u1", MESSAGE]);
  return messages[1]?.parts[0];
}

describe("section 9, the answer to an approval survives a snapshot", () => {
  it("keeps an approved call's approval once its output arrives", () => {
    const part = callOf([
      PROMPT,
      ...ASKED,
      ...answered({
        type: "tool-output-available",
        toolCallId: CALL,
        output: "wiped everything",
      }),
    ]);

    expect(part).toEqual({
      type: "tool-wipe",
      toolCallId: CALL,
      state: "output-available",
      input: INPUT,
      output: "wiped everything",
      approval: { id: APPROVAL, approved: true },
    });
  });

  it("carries no approval on a re-entered call, as the SDK types input-available", () => {
    const part = callOf([PROMPT, ...ASKED, ...answered().slice(0, 2)]);

    expect(part).toEqual({
      type: "tool-wipe",
      toolCallId: CALL,
      state: "input-available",
      input: INPUT,
    });
  });

  it("keeps an approved call's approval when the call fails", () => {
    const part = callOf([
      PROMPT,
      ...ASKED,
      ...answered({ type: "tool-output-error", toolCallId: CALL, errorText: "boom" }),
    ]);

    expect(part).toEqual({
      type: "tool-wipe",
      toolCallId: CALL,
      state: "output-error",
      input: INPUT,
      errorText: "boom",
      approval: { id: APPROVAL, approved: true },
    });
  });

  it("keeps a refused call's approval as a refusal", () => {
    const part = callOf([
      PROMPT,
      ...ASKED,
      ...answered({ type: "tool-output-denied", toolCallId: CALL }),
    ]);

    expect(part).toEqual({
      type: "tool-wipe",
      toolCallId: CALL,
      state: "output-denied",
      input: INPUT,
      approval: { id: APPROVAL, approved: false },
    });
  });

  it("gives a call that asked for no approval no approval key", () => {
    const part = callOf([
      PROMPT,
      { type: "start", messageId: MESSAGE },
      { type: "tool-input-start", toolCallId: CALL, toolName: "wipe" },
      {
        type: "tool-input-available",
        toolCallId: CALL,
        toolName: "wipe",
        input: INPUT,
      },
      { type: "tool-output-available", toolCallId: CALL, output: "wiped everything" },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(part).not.toHaveProperty("approval");
    expect(part).toEqual({
      type: "tool-wipe",
      toolCallId: CALL,
      state: "output-available",
      input: INPUT,
      output: "wiped everything",
    });
  });
});
