import { describe, expect, it } from "vitest";

import captured from "../../src/protocol/captured.json" with { type: "json" };
import { isKnownChunkKind } from "../../src/core/chunks.ts";
import { HANDLED_CHUNK_KINDS, reduceTurn } from "../../src/core/reduce.ts";
import { HANDLED_ENVELOPE_KINDS } from "../../src/core/snapshot.ts";
import { PROTOCOL_VERSION } from "../../src/protocol/version.ts";

describe("section 5.1, the chunk vocabulary", () => {
  it("answers to every chunk kind the document defines", () => {
    const unhandled = captured.chunkKinds.filter(
      (kind) => !HANDLED_CHUNK_KINDS.has(kind),
    );

    expect(unhandled).toEqual([]);
  });

  it("claims no chunk kind the document does not define", () => {
    const known = new Set(captured.chunkKinds);
    const invented = [...HANDLED_CHUNK_KINDS].filter((kind) => !known.has(kind));

    expect(invented).toEqual([]);
  });
});

describe("section 10, what a client recognises", () => {
  it("recognises every chunk kind this protocol version defines", () => {
    const unknown = captured.chunkKinds.filter((kind) => !isKnownChunkKind(kind));

    expect(unknown).toEqual([]);
  });

  it("recognises every data part kind, and any an assistant registers", () => {
    for (const kind of [...captured.dataPartKinds, "data-registered-by-an-assistant"]) {
      expect(isKnownChunkKind(kind)).toBe(true);
    }
  });

  it("does not recognise a kind a later version added", () => {
    expect(isKnownChunkKind("invented-by-a-later-version")).toBe(false);
  });

  it("reports the version it was built from", () => {
    expect(PROTOCOL_VERSION).toBe(captured.version);
  });
});

describe("section 5.2, data parts", () => {
  // `data-tool-summary` patches the call it names instead of appending, under
  // the rule section 9 states for it.
  const APPENDING = captured.dataPartKinds.filter(
    (kind) => kind !== "data-tool-summary",
  );

  it("reduces every appending data part kind the document defines to a part", () => {
    for (const kind of APPENDING) {
      const message = reduceTurn([
        { type: "start", messageId: "m" },
        { type: kind, data: { probe: kind } },
      ]);

      expect(message.parts).toEqual([{ type: kind, data: { probe: kind } }]);
    }
  });

  it("appends no part for the one kind section 9 says patches a call", () => {
    const message = reduceTurn([
      { type: "start", messageId: "m" },
      { type: "data-tool-summary", data: { toolCallId: "call_1", summary: "3 rows" } },
    ]);

    expect(message.parts).toEqual([]);
  });
});

describe("section 5.3, log envelopes", () => {
  it("reads every envelope kind the document defines", () => {
    const unhandled = captured.envelopeKinds.filter(
      (kind) => !HANDLED_ENVELOPE_KINDS.has(kind),
    );

    expect(unhandled).toEqual([]);
  });
});

describe("section 6, finish reasons", () => {
  it("carries through every value the document defines", () => {
    for (const reason of captured.finishReasons) {
      const message = reduceTurn([
        { type: "start", messageId: "m" },
        { type: "finish", finishReason: reason },
      ]);

      expect(message.finishReason).toBe(reason);
    }
  });
});
