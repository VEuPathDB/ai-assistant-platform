import {
  lastAssistantMessageIsCompleteWithApprovalResponses,
  readUIMessageStream,
  type UIMessage,
  type UIMessageChunk,
  validateUIMessages,
} from "ai";
import { describe, expect, it } from "vitest";

import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { reduceSnapshot } from "../../src/core/snapshot.ts";

const MESSAGE = "aaaaaaaa-0000-4000-8000-000000000001";
const CALL = "call_separate";
const APPROVAL = "approval_separate";
const INPUT = { controls: 12 };

const PROMPT: ProtocolChunk = {
  type: "user-message",
  message: { id: "u1", role: "user", parts: [] },
};

const ASKED: ProtocolChunk[] = [
  { type: "start", messageId: MESSAGE },
  { type: "start-step" },
  { type: "tool-input-start", toolCallId: CALL, toolName: "separate_controls" },
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "separate_controls",
    input: INPUT,
  },
  { type: "tool-approval-request", toolCallId: CALL, approvalId: APPROVAL },
  { type: "finish-step" },
  { type: "finish", finishReason: "other" },
  { type: "done" },
];

function answer(approved: boolean): ProtocolChunk {
  return {
    type: "data-tool-approval",
    id: APPROVAL,
    data: { toolCallId: CALL, approvalId: APPROVAL, approved },
  };
}

const RUNNING: ProtocolChunk[] = [
  { type: "start", messageId: MESSAGE },
  answer(true),
  {
    type: "tool-input-available",
    toolCallId: CALL,
    toolName: "separate_controls",
    input: INPUT,
  },
  { type: "data-background-task-started", data: { taskId: "t1" } },
  { type: "finish", finishReason: "other" },
  { type: "done" },
];

const RECORD = {
  type: "data-tool-approval",
  id: APPROVAL,
  data: { toolCallId: CALL, approvalId: APPROVAL, approved: true },
};

function assistantOf(chunks: ProtocolChunk[]): UIMessage {
  const message = reduceSnapshot(chunks).find((each) => each.role === "assistant");
  if (message === undefined) throw new Error("no assistant message");
  return message;
}

async function replayed(chunks: ProtocolChunk[]): Promise<UIMessage> {
  const wire = chunks.filter((chunk) => chunk.type !== "done") as UIMessageChunk[];
  const stream = new ReadableStream<UIMessageChunk>({
    start(controller) {
      for (const chunk of wire) controller.enqueue(chunk);
      controller.close();
    },
  });
  let last: UIMessage | undefined;
  for await (const message of readUIMessageStream({ stream })) last = message;
  if (last === undefined) throw new Error("the replay built no message");
  return { ...last, role: "assistant" };
}

describe("section 6.2, the answer to an approval is on the log", () => {
  it("keeps the answer beside a call that still runs after a snapshot", () => {
    const message = assistantOf([PROMPT, ...ASKED, ...RUNNING]);

    expect(message.parts).toEqual([
      { type: "step-start" },
      {
        type: "tool-separate_controls",
        toolCallId: CALL,
        state: "input-available",
        input: INPUT,
      },
      RECORD,
      { type: "data-background-task-started", data: { taskId: "t1" } },
    ]);
  });

  it("rebuilds a message the SDK schema accepts and does not send again", async () => {
    const message = assistantOf([PROMPT, ...ASKED, ...RUNNING]);

    await expect(validateUIMessages({ messages: [message] })).resolves.toHaveLength(1);
    expect(
      lastAssistantMessageIsCompleteWithApprovalResponses({ messages: [message] }),
    ).toBe(false);
  });

  it("keeps the answer on a replay through the SDK and does not send again", async () => {
    const message = await replayed([...ASKED, ...RUNNING]);

    expect(message.parts).toContainEqual(RECORD);
    expect(
      message.parts.filter((part) => part.type === "tool-separate_controls"),
    ).toMatchObject([{ state: "input-available" }]);
    expect(
      lastAssistantMessageIsCompleteWithApprovalResponses({ messages: [message] }),
    ).toBe(false);
  });

  it("records a refusal beside the denied call", () => {
    const message = assistantOf([
      PROMPT,
      ...ASKED,
      { type: "start", messageId: MESSAGE },
      answer(false),
      {
        type: "tool-input-available",
        toolCallId: CALL,
        toolName: "separate_controls",
        input: INPUT,
      },
      { type: "tool-output-denied", toolCallId: CALL },
      { type: "finish", finishReason: "stop" },
      { type: "done" },
    ]);

    expect(message.parts.slice(1)).toEqual([
      {
        type: "tool-separate_controls",
        toolCallId: CALL,
        state: "output-denied",
        input: INPUT,
        approval: { id: APPROVAL, approved: false },
      },
      { ...RECORD, data: { ...RECORD.data, approved: false } },
    ]);
  });
});
