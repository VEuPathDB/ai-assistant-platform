import { describe, expect, it } from "vitest";

import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import { reduceSnapshot } from "../../src/core/snapshot.ts";

const SUSPENDED = "aaaaaaaa-0000-4000-8000-000000000001";
const RESUMED = "bbbbbbbb-0000-4000-8000-000000000002";
const CALL = "call_consult_user";

const ASKED: ProtocolChunk[] = [
  { type: "start", messageId: SUSPENDED },
  { type: "tool-input-start", toolCallId: CALL, toolName: "consult_user" },
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "consult_user",
    input: { question: "Which orthologs?" },
  },
  { type: "tool-approval-request", toolCallId: CALL, approvalId: "ap1" },
  { type: "finish", finishReason: "stop" },
  { type: "done" },
];

/** The resumed turn re-enters the call on its input alone. */
const ANSWERED: ProtocolChunk[] = [
  { type: "start", messageId: RESUMED },
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "consult_user",
    input: { question: "Which orthologs?" },
  },
  {
    type: "tool-output-available",
    toolCallId: CALL,
    output: { answer: "P. falciparum" },
  },
  { type: "finish", finishReason: "stop" },
  { type: "done" },
];

const THREAD: ProtocolChunk[] = [
  { type: "user-message", message: { id: "u1", role: "user", parts: [] } },
  ...ASKED,
  ...ANSWERED,
];

describe("section 6.2, a turn suspended on an approval", () => {
  it("holds the call in approval-requested until the user answers", () => {
    const suspended = reduceSnapshot(THREAD)[1];

    expect(suspended?.id).toBe(SUSPENDED);
    expect(suspended?.parts).toEqual([
      {
        type: "tool-consult_user",
        toolCallId: CALL,
        state: "approval-requested",
        input: { question: "Which orthologs?" },
        approval: { id: "ap1" },
      },
    ]);
  });

  it("opens the resumed call on its input alone, with no second start", () => {
    expect(ANSWERED.map((chunk) => chunk.type)).toEqual([
      "start",
      "tool-input-available",
      "tool-output-available",
      "finish",
      "done",
    ]);
    expect(reduceTurn(ANSWERED).parts).toEqual([
      {
        type: "tool-consult_user",
        toolCallId: CALL,
        state: "output-available",
        input: { question: "Which orthologs?" },
        output: { answer: "P. falciparum" },
      },
    ]);
  });

  it("reads the answered call on the resumed message of the thread", () => {
    const messages = reduceSnapshot(THREAD);

    expect(messages).toHaveLength(3);
    expect(messages[2]?.id).toBe(RESUMED);
    expect(messages[2]?.parts.map((part) => part.type)).toEqual(["tool-consult_user"]);
  });
});
