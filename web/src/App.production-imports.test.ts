import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = dirname(fileURLToPath(import.meta.url));
const importPattern = /(?:from\s+|import\s*\(\s*|import\s+)["']([^"']+)["']\s*\)?/g;

function resolveSource(from: string, specifier: string): string | null {
  if (!specifier.startsWith("@/") && !specifier.startsWith(".")) return null;
  const base = specifier.startsWith("@/")
    ? resolve(srcRoot, specifier.slice(2))
    : resolve(dirname(from), specifier);
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    resolve(base, "index.ts"),
    resolve(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function productionSources(entry: string): string[] {
  const visited = new Set<string>();
  const pending = [entry];
  while (pending.length > 0) {
    const source = pending.pop();
    if (!source || visited.has(source)) continue;
    visited.add(source);
    const contents = readFileSync(source, "utf8");
    for (const match of contents.matchAll(importPattern)) {
      const dependency = resolveSource(source, match[1]);
      if (dependency) pending.push(dependency);
    }
  }
  return [...visited];
}

describe("production import graph", () => {
  it("keeps legacy Teams pages, components, APIs, and hooks out of production", () => {
    const sources = productionSources(resolve(srcRoot, "App.tsx"));
    const legacyTeams = sources
      .map((source) => source.slice(srcRoot.length + 1))
      .filter((source) =>
        /^(?:pages\/TeamsPage\.tsx|pages\/TeamDetailPage\.tsx|components\/teams\/|lib\/teamsApi\.ts|hooks\/useTeams\.ts)$/.test(
          source,
        ),
      );

    expect(legacyTeams).toEqual([]);
  });

  it("does not introduce Agent Teams terminology in English or Chinese UI copy", () => {
    const localeSources = [
      resolve(srcRoot, "i18n/locales/en/agents.json"),
      resolve(srcRoot, "i18n/locales/zh-CN/agents.json"),
    ].map((source) => readFileSync(source, "utf8"));

    expect(localeSources.join("\n")).not.toMatch(/Agent Teams?|智能体(?:团队|小队)/i);
  });
});
