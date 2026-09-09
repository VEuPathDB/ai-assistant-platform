import { AbstractChat, type ChatState, type ChatStatus, type UIMessage } from "ai";

import { DurableChatTransport } from "../../src/ai-sdk/DurableChatTransport.ts";
import { resumeDurableThread } from "../../src/ai-sdk/resumeDurableThread.ts";
import { type CursorStore, memoryCursorStore } from "../../src/core/cursor.ts";
import { DONE_PAYLOAD, frameText } from "../../src/core/sse.ts";

export const TASK = "00000000-0000-0000-0000-0000000000bb";
const SECOND_TASK = "00000000-0000-0000-0000-0000000000cc";
export const EARLIER = "22222222-2222-2222-2222-222222222222";
export const SUSPENDED = "33333333-3333-3333-3333-333333333333";
export const RESUMED = "44444444-4444-4444-4444-444444444444";
export const RESUSPENDED = "55555555-5555-5555-5555-555555555555";

export const FIRST_CURSOR = 1_000_000_000_001;

export interface LogEntry {
  cursor: number;
  text: string;
  done: boolean;
}

/** One thread's log, cursored the way a deployment writes it. */
export function logOf(payloads: unknown[]): LogEntry[] {
  return payloads.map((payload, index) => {
    const cursor = FIRST_CURSOR + index;
    const done = payload === DONE_PAYLOAD;
    return {
      cursor,
      done,
      text: frameText(cursor, done ? DONE_PAYLOAD : JSON.stringify(payload)),
    };
  });
}

export const COMPLETED_TURN = [
  { type: "start", messageId: EARLIER },
  { type: "text-start", id: "e1" },
  { type: "text-delta", id: "e1", delta: "Ninety-one rows." },
  { type: "text-end", id: "e1" },
  { type: "finish", finishReason: "stop" },
  DONE_PAYLOAD,
];

export const SUSPENDING_TURN = [
  { type: "start", messageId: SUSPENDED },
  {
    type: "data-background-task-started",
    data: { taskId: TASK, toolName: "add" },
  },
  { type: "finish", finishReason: "other" },
  DONE_PAYLOAD,
];

const FIRST_GAP = [
  { type: "data-task-progress", id: TASK, data: { taskId: TASK, percent: 0.9 } },
  { type: "data-task-completed", data: { taskId: TASK, status: "success" } },
];

const FINAL_TURN = [
  { type: "start", messageId: RESUMED },
  { type: "text-start", id: "c1" },
  { type: "text-delta", id: "c1", delta: "Variant B scored best." },
  { type: "text-end", id: "c1" },
  { type: "finish", finishReason: "stop" },
  DONE_PAYLOAD,
];

export const GAP_AND_CONTINUATION = [...FIRST_GAP, ...FINAL_TURN];

/** A completion turn that suspends again on a second durable task. */
const RESUSPENDING_TURN = [
  { type: "start", messageId: RESUSPENDED },
  {
    type: "data-background-task-started",
    data: { taskId: SECOND_TASK, toolName: "fetch_rows" },
  },
  { type: "finish", finishReason: "other" },
  DONE_PAYLOAD,
];

const SECOND_GAP = [
  {
    type: "data-task-progress",
    id: SECOND_TASK,
    data: { taskId: SECOND_TASK, percent: 0.9 },
  },
  { type: "data-task-completed", data: { taskId: SECOND_TASK, status: "success" } },
];

export const SUSPENDED_THREAD = logOf([...SUSPENDING_TURN, ...GAP_AND_CONTINUATION]);
export const SUSPENDING_TAIL = SUSPENDED_THREAD.slice(0, SUSPENDING_TURN.length);
export const SUSPENDED_START = FIRST_CURSOR - 1;
export const SUSPENDED_DONE = FIRST_CURSOR + SUSPENDING_TURN.length - 1;

/** Two durable suspensions on one thread, each closed by its own gap. */
export const TWICE_SUSPENDED_THREAD = logOf([
  ...SUSPENDING_TURN,
  ...FIRST_GAP,
  ...RESUSPENDING_TURN,
  ...SECOND_GAP,
  ...FINAL_TURN,
]);

export const RESUSPENDED_DONE =
  FIRST_CURSOR +
  SUSPENDING_TURN.length +
  FIRST_GAP.length +
  RESUSPENDING_TURN.length -
  1;

export const RESUSPENDED_PARTS = [
  "data-background-task-started",
  "data-task-progress",
  "data-task-completed",
];

/** Seed a store the way a snapshot of a thread suspended on a task leaves it. */
export function seedSuspended(
  store: CursorStore,
  bounds: { after: number; done: number },
): CursorStore {
  store.write("c1", bounds.done);
  store.writeOpenMessage("c1", { messageId: SUSPENDED, after: bounds.after });
  return store;
}

export function bodyOf(entries: LogEntry[]): string {
  return entries.map((entry) => entry.text).join("");
}

/** Section 4 and `event_stream.py`: a tail ends at the first `done` it serves. */
export function tailFrom(thread: LogEntry[], after: number): Response {
  const remainder = thread.filter((entry) => entry.cursor > after);
  if (remainder.length === 0) return new Response(null, { status: 204 });
  const end = remainder.findIndex((entry) => entry.done);
  const served = end === -1 ? remainder : remainder.slice(0, end + 1);
  return sseResponse(bodyOf(served));
}

export function sseResponse(body: BodyInit): Response {
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
  /** Every request the transport made, in order. */
  requests: { url: string; init: RequestInit | undefined }[];
  shape: () => { id: string; role: string; parts: string[] }[];
  resume: () => Promise<void>;
}

interface HarnessOptions {
  thread?: LogEntry[];
  post?: LogEntry[];
  cursors?: CursorStore;
  holds?: UIMessage[];
  headers?: Record<string, string>;
  /** Answer a tail directly, for a host the log fixture cannot describe. */
  respond?: (after: number, init: RequestInit | undefined) => Response;
}

/**
 * A host on one thread, served by a log that answers a tail from its cursor.
 * Its fetch rejects an aborted request the way a real one does.
 */
export function harness(options: HarnessOptions = {}): Harness {
  const thread = options.thread ?? [];
  const requests: { url: string; init: RequestInit | undefined }[] = [];
  const urls: string[] = [];
  const transport = new DurableChatTransport<UIMessage>({
    api: "/api/v1/chat",
    conversationId: "c1",
    eventsUrlFor: (id) => `/api/v1/conversations/${id}/events`,
    cursors: options.cursors ?? memoryCursorStore(),
    ...(options.headers === undefined ? {} : { headers: options.headers }),
    fetch: (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      urls.push(url);
      requests.push({ url, init });
      if (options.post !== undefined && url.startsWith("/api/v1/chat")) {
        return Promise.resolve(sseResponse(bodyOf(options.post)));
      }
      if (init?.signal?.aborted === true) {
        return Promise.reject(
          new DOMException("The operation was aborted.", "AbortError"),
        );
      }
      const after = Number.parseInt(
        new URL(url, "http://host").searchParams.get("after") ?? "0",
        10,
      );
      if (options.respond !== undefined) {
        return Promise.resolve(options.respond(after, init));
      }
      return Promise.resolve(tailFrom(thread, after));
    },
  });
  const chat = new ProbeChat(transport);
  if (options.holds !== undefined) chat.messages = options.holds;
  return {
    chat,
    transport,
    urls,
    requests,
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

export const SUSPENDED_PARTS = [
  "data-background-task-started",
  "data-task-progress",
  "data-task-completed",
];

export function heldSuspendedMessage(): UIMessage {
  return {
    id: SUSPENDED,
    role: "assistant",
    parts: [
      {
        type: "data-background-task-started",
        data: { taskId: TASK, toolName: "add" },
      },
    ],
  };
}
