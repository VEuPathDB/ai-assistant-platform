import { describe, expect, it } from "vitest";

import { buildTurnRequestBody } from "../../src/core/requestBody.ts";

interface Msg {
  id: string;
}

const base = {
  conversationId: "c1",
  id: "req-1",
  trigger: "submit-message",
  messages: [] as Msg[],
};

describe("buildTurnRequestBody", () => {
  it("names the thread, the request, the trigger and the messages", () => {
    expect(buildTurnRequestBody(base)).toEqual({
      conversationId: "c1",
      id: "req-1",
      trigger: "submit-message",
      messages: [],
    });
  });

  it("carries the messages through untouched", () => {
    const messages = [{ id: "m1" }, { id: "m2" }];

    expect(buildTurnRequestBody({ ...base, messages }).messages).toBe(messages);
  });

  it("merges a caller's base body under the fields the turn needs", () => {
    const body = buildTurnRequestBody({
      ...base,
      baseBody: { extra: "kept", conversationId: "overridden" },
    });

    expect(body["extra"]).toBe("kept");
    expect(body.conversationId).toBe("c1");
  });

  it("adds the host's own fields", () => {
    const body = buildTurnRequestBody({ ...base, extra: { siteId: "plasmodb" } });

    expect(body["siteId"]).toBe("plasmodb");
  });

  it("omits a host field the host had nothing to say about", () => {
    const body = buildTurnRequestBody({ ...base, extra: { phaseModels: undefined } });

    expect("phaseModels" in body).toBe(false);
  });

  it("omits an empty map, which the runtime reads as a set of choices", () => {
    const body = buildTurnRequestBody({ ...base, extra: { phaseModels: {} } });

    expect("phaseModels" in body).toBe(false);
  });

  it("keeps a non-empty map", () => {
    const body = buildTurnRequestBody({
      ...base,
      extra: { phaseModels: { lead: "openai:gpt-5.6-luna" } },
    });

    expect(body["phaseModels"]).toEqual({ lead: "openai:gpt-5.6-luna" });
  });

  it("keeps a falsy scalar, which is a value and not an absence", () => {
    const body = buildTurnRequestBody({ ...base, extra: { retry: false, attempt: 0 } });

    expect(body["retry"]).toBe(false);
    expect(body["attempt"]).toBe(0);
  });

  it("keeps an empty array, which is not an empty map", () => {
    const body = buildTurnRequestBody({ ...base, extra: { tags: [] } });

    expect(body["tags"]).toEqual([]);
  });
});
