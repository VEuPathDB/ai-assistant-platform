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
    const opened = transport.takeHeldTurn();
    if (opened === undefined) return;
    target.setMessages((messages) => [
      ...messages,
      { id: opened, role: "assistant", parts: [] },
    ]);
  }
}
