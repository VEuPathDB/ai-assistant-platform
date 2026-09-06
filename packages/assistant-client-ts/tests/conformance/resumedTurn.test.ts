import { AbstractChat, type ChatState, type ChatStatus, type UIMessage } from "ai";
import { describe, expect, it } from "vitest";

import { DurableChatTransport } from "../../src/ai-sdk/DurableChatTransport.ts";
import { resumeDurableThread } from "../../src/ai-sdk/resumeDurableThread.ts";
import { memoryCursorStore } from "../../src/core/cursor.ts";
import { DONE_PAYLOAD, frameText } from "../../src/core/sse.ts";

const TASK = "00000000-0000-0000-0000-0000000000bb";
const SUSPENDED = "33333333-3333-3333-3333-333333333333";
const RESUMED = "44444444-4444-4444-4444-444444444444";

function frames(...payloads: unknown[]): string {
  let cursor = 1_000_000_000_000;
  return payloads
    .map((payload) => {
      cursor += 1;
      return frameText(
        cursor,
        payload === DONE_PAYLOAD ? DONE_PAYLOAD : JSON.stringify(payload),
      );
    })
    .join("");
}

const SUSPENDING_TURN = frames(
  { type: "start", messageId: SUSPENDED },
  {
    type: "data-background-task-started",
    data: { taskId: TASK, toolName: "optimize_search_parameters" },
  },
  { type: "finish", finishReason: "other" },
  DONE_PAYLOAD,
);

const GAP_AND_CONTINUATION = frames(
  { type: "data-task-progress", id: TASK, data: { taskId: TASK, percent: 0.9 } },
  { type: "data-task-completed", data: { taskId: TASK, status: "success" } },
  { type: "start", messageId: RESUMED },
  { type: "text-start", id: "c1" },
  { type: "text-delta", id: "c1", delta: "Variant B scored best." },
  { type: "text-end", id: "c1" },
  { type: "finish", finishReason: "stop" },
  DONE_PAYLOAD,
);

const IN_FLIGHT_TURN = frames(
  { type: "start", messageId: RESUMED },
  { type: "text-start", id: "c1" },
  { type: "text-delta", id: "c1", delta: "Still working." },
);

function sseResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "x-vercel-ai-ui-message-stream": "v1",
    },
  });
}

/** The chat state a host holds, with the deep copy the SDK's own hosts make. */
class ProbeState implements ChatState<UIMessage> {
  status: ChatStatus = "ready";
  error: Error | undefined = undefined;
  messages: UIMessage[] = [];
  pushMessage = (message: UIMessage): void => {
    this.messages = this.messages.concat(message);
  };
  popMessage = (): void => {
    this.messages = this.messages.slice(0, -1);
  };
  replaceMessage = (index: number, message: UIMessage): void => {
    this.messages = [
      ...this.messages.slice(0, index),
      this.snapshot(message),
      ...this.messages.slice(index + 1),
    ];
  };
  snapshot = <T>(value: T): T => structuredClone(value);
}

class ProbeChat extends AbstractChat<UIMessage> {
  constructor(transport: DurableChatTransport<UIMessage>) {
    super({ id: "c1", transport, state: new ProbeState() });
  }
}

interface Harness {
  chat: ProbeChat;
  transport: DurableChatTransport<UIMessage>;
  urls: string[];
  shape: () => { id: string; role: string; parts: string[] }[];
  resume: () => Promise<void>;
}

function harness(bodies: string[], openMessageId?: string): Harness {
  const urls: string[] = [];
  const transport = new DurableChatTransport<UIMessage>({
    api: "/api/v1/chat",
    conversationId: "c1",
    eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
    cursors: memoryCursorStore(),
    ...(openMessageId === undefined ? {} : { openMessageId }),
    fetch: (input) => {
      urls.push(input instanceof Request ? input.url : String(input));
      const body = bodies.shift();
      return Promise.resolve(
        body === undefined ? new Response(null, { status: 204 }) : sseResponse(body),
      );
    },
  });
  const chat = new ProbeChat(transport);
  return {
    chat,
    transport,
    urls,
    shape: () =>
      chat.messages.map((message) => ({
        id: message.id,
        role: message.role,
        parts: message.parts.map((part) => part.type),
      })),
    resume: () =>
      resumeDurableThread(
        {
          setMessages: (update) => {
            chat.messages = update(chat.messages);
          },
          resumeStream: () => chat.resumeStream(),
        },
        transport,
      ),
  };
}

describe("a tail that crosses a turn boundary", () => {
  it("reads the continuation as its own message, and copies no part into it", async () => {
    const probe = harness([SUSPENDING_TURN, GAP_AND_CONTINUATION]);

    await probe.chat.sendMessage({ text: "optimize the search parameters" });
    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: probe.chat.messages[0]?.id ?? "", role: "user", parts: ["text"] },
      {
        id: SUSPENDED,
        role: "assistant",
        parts: [
          "data-background-task-started",
          "data-task-progress",
          "data-task-completed",
        ],
      },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("reads the whole tail on one connection", async () => {
    const probe = harness([SUSPENDING_TURN, GAP_AND_CONTINUATION]);

    await probe.chat.sendMessage({ text: "optimize the search parameters" });
    await probe.resume();

    expect(probe.urls).toEqual([
      "/api/v1/chat",
      "/api/v1/conversations/c1/events?after=1000000000004",
    ]);
  });

  it("finds the boundary from the message a reload already holds", async () => {
    const probe = harness([GAP_AND_CONTINUATION], SUSPENDED);
    probe.chat.messages = [
      {
        id: SUSPENDED,
        role: "assistant",
        parts: [
          {
            type: "data-background-task-started",
            data: { taskId: TASK, toolName: "optimize_search_parameters" },
          },
        ],
      },
    ];

    await probe.resume();

    expect(probe.shape()).toEqual([
      {
        id: SUSPENDED,
        role: "assistant",
        parts: [
          "data-background-task-started",
          "data-task-progress",
          "data-task-completed",
        ],
      },
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
  });

  it("keeps a resumed stream that opens the turn on one message", async () => {
    const probe = harness([IN_FLIGHT_TURN]);

    await probe.resume();

    expect(probe.shape()).toEqual([
      { id: RESUMED, role: "assistant", parts: ["text"] },
    ]);
    expect(probe.urls).toEqual(["/api/v1/conversations/c1/events?after=0"]);
  });

  it("ends when the thread has no turn in flight", async () => {
    const probe = harness([]);

    await probe.resume();

    expect(probe.shape()).toEqual([]);
  });
});
