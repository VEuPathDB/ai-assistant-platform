import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PACKAGE_ROOT = fileURLToPath(new URL("../..", import.meta.url));

interface PackageManifest {
  readonly dependencies?: Record<string, string>;
  readonly peerDependencies?: Record<string, string>;
  readonly peerDependenciesMeta?: Record<string, { readonly optional?: boolean }>;
  readonly exports: Record<string, { readonly types: string; readonly import: string }>;
  readonly files?: readonly string[];
  readonly scripts: Record<string, string>;
}

const manifest = JSON.parse(
  readFileSync(join(PACKAGE_ROOT, "package.json"), "utf8"),
) as PackageManifest;

const RINGS = [
  { subpath: ".", entry: "index" },
  { subpath: "./ai-sdk", entry: "ai-sdk" },
  { subpath: "./legacy", entry: "legacy" },
] as const;

const SOURCES = readdirSync(join(PACKAGE_ROOT, "src"), {
  recursive: true,
  encoding: "utf8",
}).filter((name) => name.endsWith(".ts"));

const SPECIFIER = /(?:from\s+"([^"]+)"|import\(\s*"([^"]+)")/g;

function bareSpecifiers(relativePath: string): string[] {
  const source = readFileSync(join(PACKAGE_ROOT, "src", relativePath), "utf8");
  return [...source.matchAll(SPECIFIER)]
    .map((match) => match[1] ?? match[2] ?? "")
    .filter((specifier) => !specifier.startsWith("."));
}

describe("the packed artifact", () => {
  it("exposes the three rings from dist, types first", () => {
    expect(Object.keys(manifest.exports)).toEqual(RINGS.map((ring) => ring.subpath));

    for (const { subpath, entry } of RINGS) {
      expect(existsSync(join(PACKAGE_ROOT, "src", `${entry}.ts`))).toBe(true);
      expect(manifest.exports[subpath]).toEqual({
        types: `./dist/${entry}.d.ts`,
        import: `./dist/${entry}.js`,
      });
    }
  });

  it("ships the build output and nothing else", () => {
    expect(manifest.files).toEqual(["dist"]);
  });

  it("rebuilds before it packs", () => {
    expect(manifest.scripts["prepack"]).toContain("build");
  });
});

describe("the dependency-free core", () => {
  it("declares no runtime dependency", () => {
    expect(manifest.dependencies).toBeUndefined();
  });

  it("declares the AI SDK as an optional peer", () => {
    expect(manifest.peerDependencies?.["ai"]).toBeDefined();
    expect(manifest.peerDependenciesMeta?.["ai"]?.optional).toBe(true);
  });

  it("imports nothing outside the package except from the ai-sdk ring", () => {
    const offenders = SOURCES.filter(
      (name) => !name.startsWith("ai-sdk/") && bareSpecifiers(name).length > 0,
    );

    expect(offenders).toEqual([]);
  });

  it("confines the AI SDK import to the ai-sdk ring", () => {
    const specifiers = SOURCES.filter((name) => name.startsWith("ai-sdk/")).flatMap(
      (name) => bareSpecifiers(name),
    );

    expect([...new Set(specifiers)]).toEqual(["ai"]);
  });
});
