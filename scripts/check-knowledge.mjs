#!/usr/bin/env node
/**
 * OKF v0.2 conformance check for docs/knowledge.
 *
 * Conformance (fails the build):
 *   1. every non-reserved .md parses as YAML frontmatter + body
 *   2. every frontmatter block carries a non-empty `type`
 *   3. reserved names (index.md, log.md) are not concepts; only the bundle
 *      root index.md carries frontmatter, and only `okf_version`
 *
 * Maintenance (fails the build here, though OKF asks consumers to tolerate it):
 *   4. every relative link resolves
 *   5. every concept is linked from its directory's index.md
 *
 * House style (ours, not OKF):
 *   6. no em-dash, en-dash, unicode ellipsis or curly quotes in any .md
 *
 * Citations (ours, not OKF):
 *   7. a citation of another repository resolves against a checkout of it
 *      beside this one, fails when that checkout has no such path, and is
 *      reported as unverified when there is no such checkout
 *
 * The spec tells *consumers* to tolerate broken links and missing indexes in
 * bundles they did not write. This is our own bundle, so a dangling link means
 * a file moved, and an unlinked concept means someone added or finished work
 * without touching the index. Both are the exact rot this check exists to
 * catch: it is what keeps "the backlog is empty" an honest statement rather
 * than an index that forgot a file.
 *
 * `collect()` returns what it found and prints nothing, so the suite in
 * check-knowledge.test.mjs can drive it over fixtures. The CLI wrapper at the
 * bottom owns every console call and every exit code.
 */
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RESERVED = new Set(["index.md", "log.md"]);
// A citation names another repository by the prefix the bundles write. The
// value is the directory a checkout of it sits in.
const SIBLING_DIRECTORIES = new Map([
  ["pathfinder", "pathfinder"],
  ["veupathdb-py", "ai-veupathdb-client"],
  ["veupathdb-mcp", "ai-wdk-mcp"],
  ["assistant-platform", "ai-assistant-platform"],
]);
// A repository prefix, a colon, a space and a path, inside an inline code span.
// The backtick separates a citation from a sentence that starts with a word and
// a colon; the space is captured, so a citation missing it is reported.
const CITATION_RE = /`{1,2}([a-z][a-z0-9-]*):(\s*)([^`\s]+)/g;
// The directory the checkouts share, which is the one above this repository.
const SIBLINGS_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
// Escapes, not literal glyphs: the file must obey the rule it enforces, and
// U+2018 against U+2019 is not a difference anyone can review by eye.
const SMART_PUNCTUATION = new Map([
  ["\u2013", "en-dash"],
  ["\u2014", "em-dash"],
  ["\u2018", "curly quote"],
  ["\u2019", "curly quote"],
  ["\u201C", "curly quote"],
  ["\u201D", "curly quote"],
  ["\u2026", "unicode ellipsis"],
]);
const SMART_PUNCTUATION_RE = /[\u2013\u2014\u2018\u2019\u201C\u201D\u2026]/g;

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return name.endsWith(".md") ? [full] : [];
  });
}

function splitFrontmatter(text) {
  if (!text.startsWith("---\n")) return { frontmatter: null, body: text };
  const end = text.indexOf("\n---\n", 3);
  if (end === -1) return { frontmatter: null, body: text, unterminated: true };
  return { frontmatter: text.slice(4, end + 1), body: text.slice(end + 5) };
}

/** Top-level `key:` names. Enough to assert `type` without a YAML dependency. */
function topLevelKeys(frontmatter) {
  return frontmatter
    .split("\n")
    .filter((line) => /^[A-Za-z_][\w-]*\s*:/.test(line))
    .map((line) => line.slice(0, line.indexOf(":")).trim());
}

function valueOf(frontmatter, key) {
  const line = frontmatter.split("\n").find((l) => l.startsWith(`${key}:`));
  return line ? line.slice(key.length + 1).trim() : "";
}

export function markdownFiles(bundle) {
  return existsSync(bundle) ? walk(bundle) : [];
}

export function collect(bundleArg, siblingsRoot = SIBLINGS_ROOT) {
  // Absolute, because link targets resolve to absolute paths and the walk must
  // produce keys that can match them. A relative argument otherwise reports
  // every concept as unlinked, which is silent and looks like real rot.
  const bundle = resolve(bundleArg);
  const errors = [];
  const unverified = [];
  const linkedFromIndex = new Set();
  const files = markdownFiles(bundle);

  if (files.length === 0) {
    errors.push(`no markdown found under ${bundle}`);
    return { errors, unverified };
  }

  for (const file of files) {
    const rel = relative(bundle, file);
    const name = rel.split("/").pop();
    const text = readFileSync(file, "utf8");
    const { frontmatter, unterminated } = splitFrontmatter(text);

    if (RESERVED.has(name)) {
      const isBundleRootIndex = rel === "index.md";
      if (frontmatter && !isBundleRootIndex) {
        errors.push(`${rel}: reserved file must not carry frontmatter`);
      }
      if (isBundleRootIndex && frontmatter) {
        const extra = topLevelKeys(frontmatter).filter(
          (k) => k !== "okf_version",
        );
        if (extra.length > 0) {
          errors.push(
            `${rel}: bundle root index may only declare okf_version, found ${extra.join(", ")}`,
          );
        }
      }
    } else {
      if (unterminated) {
        errors.push(`${rel}: frontmatter opened but never closed`);
      } else if (!frontmatter) {
        errors.push(`${rel}: concept has no frontmatter (OKF requires a type)`);
      } else if (!valueOf(frontmatter, "type")) {
        errors.push(`${rel}: frontmatter has no non-empty type`);
      }
    }

    for (const [, target] of text.matchAll(/\]\(([^)]+)\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("#")) continue;
      const [path] = target.split("#");
      if (path === "") continue;
      const resolved = resolve(dirname(file), path);
      const ok = path.endsWith("/")
        ? existsSync(join(resolved, "index.md"))
        : existsSync(resolved);
      if (!ok) errors.push(`${rel}: link does not resolve -> ${target}`);
      if (name === "index.md") linkedFromIndex.add(resolved);
    }

    for (const [, prefix, gap, target] of text.matchAll(CITATION_RE)) {
      const directory = SIBLING_DIRECTORIES.get(prefix);
      if (directory === undefined) continue;
      if (gap === "") {
        errors.push(
          `${rel}: citation needs a space after the colon -> ${prefix}:${target}`,
        );
        continue;
      }
      // A citation may name a symbol after the path, or an anchor.
      const [path] = target.split("#")[0].split(":");
      if (path === "") continue;
      const checkout = join(siblingsRoot, directory);
      if (!existsSync(checkout)) {
        unverified.push(`${rel}: no ${directory} checkout to read -> ${prefix}: ${path}`);
      } else if (!existsSync(join(checkout, path))) {
        errors.push(`${rel}: citation does not resolve -> ${prefix}: ${path}`);
      }
    }

    // The bundle states this rule about itself, in the House style section of
    // conventions/maintaining-this-bundle.md. A rule the bundle states about
    // itself and then does not check is the rot this script exists to catch: two
    // em-dashes sat in decisions/ until someone swept for them by hand. Only
    // punctuation is flagged, never other non-ASCII, because an accented proper
    // name is legitimate and the convention is about punctuation.
    text.split("\n").forEach((line, index) => {
      for (const match of line.matchAll(SMART_PUNCTUATION_RE)) {
        errors.push(
          `${rel}:${index + 1}:${match.index + 1}: ${SMART_PUNCTUATION.get(match[0])}, house style is ASCII punctuation only`,
        );
      }
    });
  }

  // A concept nobody links from its own index is work that was added or finished
  // without the index being touched. That is how a backlog starts lying.
  for (const file of files) {
    const rel = relative(bundle, file);
    if (RESERVED.has(rel.split("/").pop())) continue;
    if (linkedFromIndex.has(file)) continue;
    const owner = join(relative(bundle, dirname(file)) || ".", "index.md");
    errors.push(`${rel}: not linked from ${owner}`);
  }

  return { errors, unverified };
}

const invokedDirectly = process.argv[1]?.endsWith("check-knowledge.mjs");
if (invokedDirectly) {
  const bundle = resolve(process.argv[2] ?? "docs/knowledge");
  const files = markdownFiles(bundle);
  if (files.length === 0) {
    console.error(`check-knowledge: no markdown found under ${bundle}`);
    process.exit(1);
  }
  const { errors, unverified } = collect(bundle);
  if (unverified.length > 0) {
    console.log(`check-knowledge: ${unverified.length} citations UNVERIFIED`);
    for (const line of unverified) console.log(`  ${line}`);
  }
  if (errors.length > 0) {
    console.error("check-knowledge: FAILED");
    for (const error of errors) console.error(`  ${error}`);
    process.exit(1);
  }
  console.log(
    `check-knowledge: ${files.length} files conform to OKF v0.2 (0 violations)`,
  );
}
