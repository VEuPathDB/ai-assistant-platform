import { describe, expect, it } from "vitest";

import captured from "../../src/protocol/captured.json" with { type: "json" };
import { type ProtocolChunk } from "../../src/core/chunks.ts";
import { reduceTurn } from "../../src/core/reduce.ts";
import { reduceSnapshot } from "../../src/core/snapshot.ts";

const TASK = "5a1f3c9e-0000-4000-8000-000000000001";
const SUSPENDED = "aaaaaaaa-0000-4000-8000-000000000001";
const RESUMED = "bbbbbbbb-0000-4000-8000-000000000002";

/** One thread whose turn suspended on a durable task and then continued. */
const THREAD: ProtocolChunk[] = [
  { type: "user-message", message: { id: "u1", role: "user", parts: [] } },
  { type: "start", messageId: SUSPENDED },
  { type: "start-step" },
  {
    type: "data-background-task-started",
    data: {
      taskId: TASK,
      toolName: "run_control_tests_on_step",
      estimatedDurationSeconds: 180,
    },
  },
  { type: "finish-step" },
  { type: "finish", finishReason: "other" },
  { type: "done" },
  {
    type: "data-task-progress",
    id: TASK,
    data: { taskId: TASK, percent: 0, message: "starting" },
  },
  {
    type: "data-task-progress",
    id: TASK,
    data: { taskId: TASK, percent: 0.5, message: "halfway" },
  },
  {
    type: "data-task-progress",
    id: TASK,
    data: { taskId: TASK, percent: 1, message: "done" },
  },
  { type: "data-task-completed", data: { taskId: TASK, status: "success" } },
  { type: "start", messageId: RESUMED },
  { type: "text-start", id: "t1" },
  { type: "text-delta", id: "t1", delta: "42 of 46 controls matched." },
  { type: "text-end", id: "t1" },
  { type: "finish", finishReason: "stop" },
  { type: "done" },
];

describe("a turn suspended on a durable task", () => {
  it("carries the whole lifecycle on the thread, in the document's order", () => {
    const seen = THREAD.map((chunk) => chunk.type).filter((type) =>
      captured.taskLifecycle.includes(type),
    );

    expect([...new Set(seen)]).toEqual(captured.taskLifecycle);
  });

  it("attaches the task's card, progress and outcome to the message that started it", () => {
    const messages = reduceSnapshot(THREAD);

    expect(messages).toHaveLength(3);
    const suspended = messages[1];
    expect(suspended?.id).toBe(SUSPENDED);
    expect(suspended?.parts.map((part) => part.type)).toEqual([
      "step-start",
      "data-background-task-started",
      "data-task-progress",
      "data-task-completed",
    ]);
  });

  it("reconciles every progress chunk for one task into one part", () => {
    const progress = reduceTurn(THREAD).parts.filter(
      (part) => part.type === "data-task-progress",
    );

    expect(progress).toEqual([
      {
        type: "data-task-progress",
        id: TASK,
        data: { taskId: TASK, percent: 1, message: "done" },
      },
    ]);
  });

  it("reads the continuation as its own message", () => {
    const messages = reduceSnapshot(THREAD);
    const resumed = messages[2];

    expect(resumed?.id).toBe(RESUMED);
    expect(resumed?.parts).toEqual([
      { type: "text", text: "42 of 46 controls matched.", state: "done" },
    ]);
  });

  it("keeps one part per lane when a task fans out", () => {
    const lanes: ProtocolChunk[] = [
      { type: "start", messageId: SUSPENDED },
      {
        type: "data-task-progress",
        id: `${TASK}:v1`,
        data: {
          taskId: TASK,
          percent: 0.2,
          message: "variant v1",
          toolSpecific: { variantId: "v1" },
        },
      },
      {
        type: "data-task-progress",
        id: `${TASK}:v2`,
        data: {
          taskId: TASK,
          percent: 0.5,
          message: "variant v2",
          toolSpecific: { variantId: "v2" },
        },
      },
      {
        type: "data-task-progress",
        id: `${TASK}:v1`,
        data: {
          taskId: TASK,
          percent: 0.8,
          message: "variant v1",
          toolSpecific: { variantId: "v1" },
        },
      },
    ];

    const progress = reduceTurn(lanes).parts.filter(
      (part) => part.type === "data-task-progress",
    );

    expect(progress).toEqual([
      {
        type: "data-task-progress",
        id: `${TASK}:v1`,
        data: {
          taskId: TASK,
          percent: 0.8,
          message: "variant v1",
          toolSpecific: { variantId: "v1" },
        },
      },
      {
        type: "data-task-progress",
        id: `${TASK}:v2`,
        data: {
          taskId: TASK,
          percent: 0.5,
          message: "variant v2",
          toolSpecific: { variantId: "v2" },
        },
      },
    ]);
  });

  it("reads a lane from the payload and never from the id", () => {
    const [part] = reduceTurn([
      { type: "start", messageId: SUSPENDED },
      {
        type: "data-task-progress",
        id: `${TASK}:v7`,
        data: {
          taskId: TASK,
          percent: 0.1,
          message: "variant v7",
          toolSpecific: { variantId: "v7" },
        },
      },
    ]).parts;

    expect(part).toEqual({
      type: "data-task-progress",
      id: `${TASK}:v7`,
      data: {
        taskId: TASK,
        percent: 0.1,
        message: "variant v7",
        toolSpecific: { variantId: "v7" },
      },
    });
  });

  it("needs no second reader: the core client sees the task without one", () => {
    const gap = THREAD.filter((chunk) => chunk.type.startsWith("data-task-"));

    expect(gap).not.toEqual([]);
    for (const chunk of gap) {
      expect(
        reduceTurn([{ type: "start", messageId: SUSPENDED }, chunk]).parts,
      ).toHaveLength(1);
    }
  });
});
