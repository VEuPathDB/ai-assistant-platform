import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { extractProtocol } from "../src/protocol/extract.ts";

const source = fileURLToPath(new URL("../../../PROTOCOL.md", import.meta.url));
const target = fileURLToPath(new URL("../src/protocol/captured.json", import.meta.url));

const captured = extractProtocol(readFileSync(source, "utf8"));
writeFileSync(target, `${JSON.stringify(captured, null, 2)}\n`);

console.log(
  `captured protocol ${captured.version}: ${String(captured.examples.length)} examples, ` +
    `${String(captured.chunkKinds.length)} chunk kinds`,
);
