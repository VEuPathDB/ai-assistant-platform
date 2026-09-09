import { describe, expect, it } from "vitest";

import type { MessageLike, PartLike } from "../../src/core/message.ts";
import {
  type TaskProgress,
  orderedLanes,
  taskLifecycle,
} from "../../src/core/tasks.ts";

const TASK = "5a1f3c9e-0000-4000-8000-000000000001";
const OTHER = "5a1f3c9e-0000-4000-8000-000000000002";

function progress(
  taskId: string,
  percent: number,
  message: string,
  toolSpecific?: Record<string, unknown>,
): PartLike {
  return {
    type: "data-task-progress",
    data:
      toolSpecific === undefined
        ? { taskId, percent, message }
        : { taskId, percent, message, toolSpecific },
  };
}

function completed(taskId: string, status: string, error?: string): PartLike {
  return {
    type: "data-task-completed",
    data: { taskId, status, error: error ?? null },
  };
}

function thread(...parts: PartLike[]): MessageLike[] {
  return [{ role: "assistant", parts }];
}

const laneOf = (update: TaskProgress): string | null => {
  const lane = update.toolSpecific?.["variantId"];
  return typeof lane === "string" ? lane : null;
};

describe("one durable task's lifecycle on the thread", () => {
  it("keeps the newest progress and the matching outcome", () => {
    const lifecycle = taskLifecycle(
      thread(
        progress(TASK, 0, "starting"),
        progress(TASK, 0.5, "halfway"),
        completed(TASK, "success"),
      ),
      TASK,
    );

    expect(lifecycle.lanes.get(null)).toEqual({
      taskId: TASK,
      percent: 0.5,
      message: "halfway",
      toolSpecific: null,
    });
    expect(lifecycle.completed).toEqual({
      taskId: TASK,
      status: "success",
      error: null,
    });
  });

  it("reads nothing off another task's chunks", () => {
    const lifecycle = taskLifecycle(
      thread(progress(OTHER, 0.9, "other"), completed(OTHER, "failed", "boom")),
      TASK,
    );

    expect(lifecycle.lanes.size).toBe(0);
    expect(lifecycle.completed).toBe(null);
  });

  it("keeps one lane per sequence when the task fans out", () => {
    const lifecycle = taskLifecycle(
      thread(
        progress(TASK, 0.2, "variant v1", { variantId: "v1" }),
        progress(TASK, 0.5, "variant v2", { variantId: "v2" }),
        progress(TASK, 0.8, "variant v1", { variantId: "v1" }),
      ),
      TASK,
      { laneOf },
    );

    expect([...lifecycle.lanes.keys()]).toEqual(["v1", "v2"]);
    expect(lifecycle.lanes.get("v1")?.percent).toBe(0.8);
    expect(lifecycle.lanes.get("v2")?.percent).toBe(0.5);
  });

  it("collapses the lanes into one when the reader names none", () => {
    const lifecycle = taskLifecycle(
      thread(
        progress(TASK, 0.2, "variant v1", { variantId: "v1" }),
        progress(TASK, 0.5, "variant v2", { variantId: "v2" }),
      ),
      TASK,
    );

    expect([...lifecycle.lanes.keys()]).toEqual([null]);
    expect(lifecycle.lanes.get(null)?.percent).toBe(0.5);
  });

  it("carries the outcome's failure text", () => {
    const lifecycle = taskLifecycle(thread(completed(TASK, "failed", "boom")), TASK);

    expect(lifecycle.completed).toEqual({
      taskId: TASK,
      status: "failed",
      error: "boom",
    });
  });

  it("refuses a status the protocol does not define, rather than read it as done", () => {
    const lifecycle = taskLifecycle(thread(completed(TASK, "SUCCESS")), TASK);

    expect(lifecycle.completed).toBe(null);
  });

  it("ignores a payload that names no task", () => {
    const lifecycle = taskLifecycle(
      thread({ type: "data-task-progress", data: { percent: 0.4, message: "no id" } }),
      TASK,
    );

    expect(lifecycle.lanes.size).toBe(0);
  });

  it("keeps a lane for an update that states neither a percent nor a message", () => {
    const lifecycle = taskLifecycle(
      thread({ type: "data-task-progress", data: { taskId: TASK } }),
      TASK,
    );

    expect(lifecycle.lanes.get(null)).toEqual({
      taskId: TASK,
      percent: null,
      message: null,
      toolSpecific: null,
    });
  });

  it("reads a task across the messages the gap left it on", () => {
    const lifecycle = taskLifecycle(
      [
        { role: "assistant", parts: [progress(TASK, 0.3, "third")] },
        { role: "user", parts: [] },
        { role: "assistant", parts: [completed(TASK, "success")] },
      ],
      TASK,
    );

    expect(lifecycle.lanes.get(null)?.percent).toBe(0.3);
    expect(lifecycle.completed?.status).toBe("success");
  });
});

describe("the lanes a card draws", () => {
  it("orders them by name", () => {
    const lifecycle = taskLifecycle(
      thread(
        progress(TASK, 0.5, "variant v2", { variantId: "v2" }),
        progress(TASK, 0.2, "variant v1", { variantId: "v1" }),
      ),
      TASK,
      { laneOf },
    );

    expect(orderedLanes(lifecycle.lanes).map(([lane]) => lane)).toEqual(["v1", "v2"]);
  });

  it("draws one lane with no update when the task has not reported yet", () => {
    expect(orderedLanes(new Map())).toEqual([[null, null]]);
  });
});
