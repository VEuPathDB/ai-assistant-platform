import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import captured from "../../src/protocol/captured.json" with { type: "json" };
import { extractProtocol } from "../../src/protocol/extract.ts";

const PROTOCOL_PATH = fileURLToPath(
  new URL("../../../../PROTOCOL.md", import.meta.url),
);

describe("the vendored protocol capture", () => {
  it("is what PROTOCOL.md says, byte for byte", () => {
    const source = readFileSync(PROTOCOL_PATH, "utf8");

    expect(extractProtocol(source)).toEqual(captured);
  });

  it("names the protocol version the document declares", () => {
    expect(captured.version).toBe("1.6.0");
  });

  it("carries one example per kind the reference assistant produces", () => {
    expect(captured.examples).toHaveLength(18);
    const kinds = captured.examples.map((example) => example.kind);
    expect(new Set(kinds).size).toBe(kinds.length);
  });

  it("separates the request's core fields from the product's own", () => {
    const core = new Set(captured.request.coreFields);
    const shared = captured.request.extensionFields.filter((field) => core.has(field));

    expect(shared).toEqual([]);
    expect(core.size).toBeGreaterThan(0);
  });

  it("captures a request example the client can send back", () => {
    const names = captured.request.examples.map((example) => example.kind);

    expect(names).toEqual(["submit-message", "approval-response"]);
  });
});
