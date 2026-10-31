import { describe, expect, it } from "vitest";

import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import { reduceSnapshot } from "../../src/core/snapshot.ts";

const MESSAGE = "aaaaaaaa-0000-4000-8000-000000000001";
const CALL = "call_consult_user";
const INPUT = { question: "Which orthologs?" };

const PROMPT: ProtocolChunk = {
  type: "user-message",
  message: { id: "u1", role: "user", parts: [] },
};

const ASKED: ProtocolChunk[] = [
  { type: "start", messageId: MESSAGE },
  { type: "tool-input-start", toolCallId: CALL, toolName: "consult_user" },
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "consult_user",
    input: INPUT,
  },
  { type: "tool-approval-request", toolCallId: CALL, approvalId: "ap1" },
  { type: "finish", finishReason: "other" },
  { type: "done" },
];

const ANSWERED: ProtocolChunk[] = [
  { type: "start", messageId: MESSAGE },
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "consult_user",
    input: INPUT,
  },
  {
    type: "tool-output-available",
    toolCallId: CALL,
    output: { answer: "P. falciparum" },
  },
  { type: "finish", finishReason: "stop" },
  { type: "done" },
];

describe("section 6.2, a turn suspended on an approval", () => {
  it("holds the call in approval-requested until the user answers", () => {
    const messages = reduceSnapshot([PROMPT, ...ASKED]);

    expect(messages.map((message) => message.id)).toEqual(["u1", MESSAGE]);
    expect(messages[1]?.parts).toEqual([
      {
        type: "tool-consult_user",
        toolCallId: CALL,
        state: "approval-requested",
        input: INPUT,
        approval: { id: "ap1" },
      },
    ]);
  });

  it("continues the open message, re-entering the call on its input alone", () => {
    expect(ANSWERED.map((chunk) => chunk.type)).toEqual([
      "start",
      "tool-input-available",
      "tool-output-available",
      "finish",
      "done",
    ]);
    expect(ANSWERED[0]).toEqual({ type: "start", messageId: MESSAGE });
  });

  it("patches the asked call in the one message the thread holds", () => {
    const messages = reduceSnapshot([PROMPT, ...ASKED, ...ANSWERED]);

    expect(messages.map((message) => message.id)).toEqual(["u1", MESSAGE]);
    expect(messages[1]?.parts).toEqual([
      {
        type: "tool-consult_user",
        toolCallId: CALL,
        state: "output-available",
        input: INPUT,
        output: { answer: "P. falciparum" },
        approval: { id: "ap1", approved: true },
      },
    ]);
  });

  it("places the call for a reader that holds only the answering turn", () => {
    expect(reduceTurn(ANSWERED).parts).toEqual([
      {
        type: "tool-consult_user",
        toolCallId: CALL,
        state: "output-available",
        input: INPUT,
        output: { answer: "P. falciparum" },
      },
    ]);
  });
});
