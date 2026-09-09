import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { collect } from "./check-knowledge.mjs";

const FIXTURES = join(
  dirname(fileURLToPath(import.meta.url)),
  "__fixtures__/knowledge",
);
const errorsFor = (name) => collect(join(FIXTURES, name));
const only = (name) => {
  const errors = errorsFor(name);
  assert.equal(errors.length, 1, `expected exactly one error, got ${errors}`);
  return errors[0];
};

test("a conformant bundle produces no errors", () => {
  assert.deepEqual(errorsFor("clean"), []);
});

test("a relative bundle path behaves the same as an absolute one", () => {
  assert.deepEqual(collect("scripts/__fixtures__/knowledge/clean"), []);
});

test("a concept with no frontmatter is rejected", () => {
  assert.match(only("no-frontmatter"), /bare\.md: concept has no frontmatter/);
});

test("frontmatter opened but never closed is rejected", () => {
  assert.match(
    only("unterminated-frontmatter"),
    /unterminated\.md: frontmatter opened but never closed/,
  );
});

test("frontmatter with an empty type is rejected", () => {
  assert.match(only("empty-type"), /typeless\.md: frontmatter has no non-empty type/);
});

test("a reserved file carrying frontmatter is rejected", () => {
  assert.match(
    only("reserved-with-frontmatter"),
    /sub\/index\.md: reserved file must not carry frontmatter/,
  );
});

test("the bundle root index may declare only okf_version", () => {
  assert.match(
    only("root-index-extra-keys"),
    /index\.md: bundle root index may only declare okf_version, found status, tags/,
  );
});

test("a link to a missing file is rejected", () => {
  assert.match(only("broken-link"), /link does not resolve/);
});

test("a directory link whose index.md is missing is rejected", () => {
  const errors = errorsFor("dir-link");
  assert.ok(
    errors.some((e) => /index\.md: link does not resolve -> hollow\//.test(e)),
    `expected an unresolved directory link, got ${errors}`,
  );
});

test("a concept no index links to is rejected", () => {
  assert.match(only("unlinked-concept"), /orphan\.md: not linked from index\.md/);
});

test("a bundle with no markdown at all is rejected", () => {
  assert.match(only("empty-bundle"), /no markdown found under /);
});

test("every smart punctuation character is flagged with file, line and column", () => {
  const errors = errorsFor("punctuation").filter((e) => /house style/.test(e));
  assert.deepEqual(errors, [
    "prose.md:6:4: em-dash, house style is ASCII punctuation only",
    "prose.md:6:13: en-dash, house style is ASCII punctuation only",
    "prose.md:7:7: curly quote, house style is ASCII punctuation only",
    "prose.md:7:14: curly quote, house style is ASCII punctuation only",
    "prose.md:7:20: curly quote, house style is ASCII punctuation only",
    "prose.md:7:27: curly quote, house style is ASCII punctuation only",
    "prose.md:8:9: unicode ellipsis, house style is ASCII punctuation only",
  ]);
});

test("all four curly quotes are flagged, not just the double pair", () => {
  // Code points, not glyphs: U+2018 against U+2019 is not reviewable by eye,
  // and this file must obey the rule it is testing.
  const CURLY = [0x2018, 0x2019, 0x201c, 0x201d];
  const text = readFileSync(join(FIXTURES, "punctuation/prose.md"), "utf8");
  for (const point of CURLY) {
    const glyph = String.fromCodePoint(point);
    const label = point.toString(16).toUpperCase();
    assert.ok(text.includes(glyph), `fixture is missing U+${label}`);
  }
  const flagged = errorsFor("punctuation").filter((e) => /curly quote/.test(e));
  assert.equal(flagged.length, CURLY.length);
});

test("two occurrences on one line are both reported", () => {
  const line6 = errorsFor("punctuation").filter((e) => /^prose\.md:6:/.test(e));
  assert.equal(line6.length, 2);
});

test("an accented proper name is not flagged", () => {
  assert.deepEqual(errorsFor("accented-name"), []);
});
