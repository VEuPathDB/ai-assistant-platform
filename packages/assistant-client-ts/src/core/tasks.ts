import { asRecord, fieldNumber, fieldString } from "./chunks.ts";
import type { MessageLike } from "./message.ts";

const PROGRESS = "data-task-progress";
const COMPLETED = "data-task-completed";

/** How a durable task ended. Section 6.1. */
export type TaskStatus = "success" | "failed";

const STATUSES: readonly TaskStatus[] = ["success", "failed"];

export interface TaskProgress {
  taskId: string;
  percent: number | null;
  message: string | null;
  /** What the producer says about this update, including the lane it names. */
  toolSpecific: Record<string, unknown> | null;
}

export interface TaskCompletion {
  taskId: string;
  status: TaskStatus;
  error: string | null;
}

/** One lane of a task and its newest update, or null when it has none yet. */
export type TaskLane = readonly [string | null, TaskProgress | null];

export interface TaskLifecycle {
  lanes: ReadonlyMap<string | null, TaskProgress>;
  completed: TaskCompletion | null;
}

export interface TaskLifecycleOptions {
  /**
   * The lane an update names. The protocol says a producer names its lane in
   * `toolSpecific` and leaves the key to the producer, so the reader supplies
   * this. Without it a task reads as one sequence.
   */
  laneOf?: (progress: TaskProgress) => string | null;
}

/** Read a progress payload, or nothing when it names no task. */
function readTaskProgress(data: unknown): TaskProgress | undefined {
  const record = asRecord(data);
  if (record === undefined) return undefined;
  const taskId = fieldString(record, "taskId");
  if (taskId === undefined) return undefined;
  return {
    taskId,
    percent: fieldNumber(record, "percent") ?? null,
    message: fieldString(record, "message") ?? null,
    toolSpecific: asRecord(record["toolSpecific"]) ?? null,
  };
}

/** Read an outcome payload, or nothing when it names no task or no status. */
function readTaskCompletion(data: unknown): TaskCompletion | undefined {
  const record = asRecord(data);
  if (record === undefined) return undefined;
  const taskId = fieldString(record, "taskId");
  const status = STATUSES.find((known) => known === record["status"]);
  if (taskId === undefined || status === undefined) return undefined;
  return { taskId, status, error: fieldString(record, "error") ?? null };
}

/**
 * One task's progress and outcome, read off the thread's own parts. The gap of
 * section 6.1 leaves both on the message that started the task, and a fan-out
 * leaves one part per lane, each advancing on its own.
 */
export function taskLifecycle(
  messages: readonly MessageLike[],
  taskId: string,
  options?: TaskLifecycleOptions,
): TaskLifecycle {
  const laneOf = options?.laneOf;
  const lanes = new Map<string | null, TaskProgress>();
  let completed: TaskCompletion | null = null;
  for (const message of messages) {
    for (const part of message.parts) {
      if (part.type === PROGRESS) {
        const update = readTaskProgress(part.data);
        if (update?.taskId === taskId) lanes.set(laneOf?.(update) ?? null, update);
      } else if (part.type === COMPLETED) {
        const outcome = readTaskCompletion(part.data);
        if (outcome?.taskId === taskId) completed = outcome;
      }
    }
  }
  return { lanes, completed };
}

/** The lanes in a stable order. A task that has not reported yet has one. */
export function orderedLanes(
  lanes: ReadonlyMap<string | null, TaskProgress>,
): readonly TaskLane[] {
  const ordered: TaskLane[] = [...lanes.entries()].sort(([left], [right]) =>
    (left ?? "").localeCompare(right ?? ""),
  );
  return ordered.length > 0 ? ordered : [[null, null]];
}
