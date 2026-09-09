import type { UIMessage } from "ai";
import { describe, expect, it } from "vitest";

import { toTraceParts } from "../../src/ai-sdk/messageParts.ts";

type UIPart = UIMessage["parts"][number];

/** What the SDK's own reducer leaves beside a call it has a summary for. */
type FoldedToolPart = UIPart & { summary?: string; summaryStatus?: string };

describe("the SDK's parts read as the protocol's", () => {
  it("keeps the parts the protocol defines", () => {
    const parts: UIPart[] = [
      { type: "text", text: "the count is 42" },
      { type: "step-start" },
      {
        type: "tool-run_control_tests_on_step",
        toolCallId: "call_1",
        state: "output-available",
        input: { stepId: 7 },
        output: { mcc: 0.81 },
      },
    ];

    expect(toTraceParts(parts)).toEqual([
      { type: "text", text: "the count is 42" },
      { type: "step-start" },
      {
        type: "tool-run_control_tests_on_step",
        toolCallId: "call_1",
        state: "output-available",
        input: { stepId: 7 },
        output: { mcc: 0.81 },
      },
    ]);
  });

  it("drops the part kinds the protocol does not name", () => {
    const parts: UIPart[] = [
      { type: "text", text: "kept" },
      { type: "custom", kind: "acme.widget" },
      { type: "reasoning-file", mediaType: "text/plain", url: "data:," },
      {
        type: "dynamic-tool",
        toolName: "whatever",
        toolCallId: "call_2",
        state: "input-available",
        input: {},
      },
    ];

    expect(toTraceParts(parts)).toEqual([{ type: "text", text: "kept" }]);
  });

  it("reads an answered approval as the call the runtime re-enters", () => {
    const parts: UIPart[] = [
      {
        type: "tool-clear_strategy",
        toolCallId: "call_clear",
        state: "approval-responded",
        input: { confirm: true },
        approval: { id: "approval_clear", approved: true },
      },
    ];

    expect(toTraceParts(parts)).toEqual([
      {
        type: "tool-clear_strategy",
        toolCallId: "call_clear",
        state: "input-available",
        input: { confirm: true },
      },
    ]);
  });

  it("keeps an open approval, with the id the answer names", () => {
    const parts: UIPart[] = [
      {
        type: "tool-clear_strategy",
        toolCallId: "call_clear",
        state: "approval-requested",
        input: {},
        approval: { id: "approval_clear" },
      },
    ];

    expect(toTraceParts(parts)).toEqual([
      {
        type: "tool-clear_strategy",
        toolCallId: "call_clear",
        state: "approval-requested",
        input: {},
        approval: { id: "approval_clear" },
      },
    ]);
  });

  it("carries the line the SDK's reducer left beside the call", () => {
    const part: FoldedToolPart = {
      type: "tool-search_genes",
      toolCallId: "call_3",
      state: "output-available",
      input: {},
      output: { count: 6 },
      summary: "6 of 12 Sample",
      summaryStatus: "empty",
    };

    expect(toTraceParts([part])).toEqual([
      {
        type: "tool-search_genes",
        toolCallId: "call_3",
        summary: "6 of 12 Sample",
        summaryStatus: "empty",
        state: "output-available",
        input: {},
        output: { count: 6 },
      },
    ]);
  });

  it("reads no line when the status is not one the protocol names", () => {
    const part: FoldedToolPart = {
      type: "tool-search_genes",
      toolCallId: "call_4",
      state: "output-available",
      input: {},
      output: null,
      summary: "6 of 12 Sample",
      summaryStatus: "green",
    };

    expect(toTraceParts([part])).toEqual([
      {
        type: "tool-search_genes",
        toolCallId: "call_4",
        state: "output-available",
        input: {},
        output: null,
      },
    ]);
  });

  it("reports the error text a failed call carries", () => {
    const parts: UIPart[] = [
      {
        type: "tool-search_genes",
        toolCallId: "call_5",
        state: "output-error",
        input: { term: "kinase" },
        errorText: "the site refused the search",
      },
    ];

    expect(toTraceParts(parts)).toEqual([
      {
        type: "tool-search_genes",
        toolCallId: "call_5",
        state: "output-error",
        input: { term: "kinase" },
        errorText: "the site refused the search",
      },
    ]);
  });
});
