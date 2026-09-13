import { type UIMessage } from "ai";

/** A transport that holds the turn a resumed stream stopped at. */
export interface HeldTurnSource {
  takeHeldTurn(): string | undefined;
}

/** The part of a chat host a durable resume drives. */
export interface DurableResumeTarget {
  setMessages: (update: (messages: UIMessage[]) => UIMessage[]) => void;
  resumeStream: () => Promise<void>;
}

/** One entry per id: the newest copy of a repeated id, at its first position. */
function oneEntryPerId(messages: UIMessage[]): UIMessage[] {
  const newest = new Map<string, UIMessage>();
  for (const message of messages) newest.set(message.id, message);
  if (newest.size === messages.length) return messages;
  const placed = new Set<string>();
  const kept: UIMessage[] = [];
  for (const message of messages) {
    if (placed.has(message.id)) continue;
    placed.add(message.id);
    kept.push(newest.get(message.id) ?? message);
  }
  return kept;
}

/** The message a resumed read stopped at, opened where the thread lacks it. */
function opened(messages: UIMessage[], messageId: string): UIMessage[] {
  if (messages.some((message) => message.id === messageId)) return messages;
  return [...messages, { id: messageId, role: "assistant", parts: [] }];
}

/**
 * Read the thread from the cursor the transport holds, across turn boundaries.
 * The SDK reads one message per stream, so each turn the tail opens is read on
 * its own resume, after the message that turn names exists to receive it.
 */
export async function resumeDurableThread(
  target: DurableResumeTarget,
  transport: HeldTurnSource,
): Promise<void> {
  for (;;) {
    await target.resumeStream();
    target.setMessages(oneEntryPerId);
    const next = transport.takeHeldTurn();
    if (next === undefined) return;
    target.setMessages((messages) => opened(messages, next));
  }
}
