import { describe, expect, it } from "vitest";
import { resources, namespaceKeys } from "./resources";

type StringEntry = [key: string, value: string];

function interpolationVariables(value: unknown): string[] {
  if (typeof value !== "string") return [];
  return [...value.matchAll(/{{\s*([^}\s]+)\s*}}/g)].map((match) => match[1]);
}

function flattenStrings(value: unknown, path: string[] = []): StringEntry[] {
  if (typeof value === "string") return [[path.join("."), value]];
  if (!value || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, child]) => flattenStrings(child, [...path, key]));
}

describe("bundled localization resources", () => {
  it("keeps namespace and key parity between English and Chinese", () => {
    expect(Object.keys(resources.en).sort()).toEqual(Object.keys(resources["zh-CN"]).sort());
    for (const namespace of namespaceKeys) {
      const english = flattenStrings(resources.en[namespace]);
      const chinese = flattenStrings(resources["zh-CN"][namespace]);
      expect(chinese.map(([key]) => key).sort(), namespace).toEqual(
        english.map(([key]) => key).sort(),
      );
    }
  });

  it("keeps interpolation variables identical between languages", () => {
    for (const namespace of namespaceKeys) {
      const english = new Map(flattenStrings(resources.en[namespace]));
      const chinese = new Map(flattenStrings(resources["zh-CN"][namespace]));
      for (const [key, value] of english) {
        expect(interpolationVariables(chinese.get(key)), `${namespace}.${key}`).toEqual(
          interpolationVariables(value),
        );
      }
    }
  });

  it("contains no empty translations", () => {
    for (const language of ["en", "zh-CN"] as const) {
      for (const namespace of namespaceKeys) {
        for (const [key, value] of flattenStrings(resources[language][namespace])) {
          expect(value.trim(), `${language}.${namespace}.${key}`).not.toBe("");
        }
      }
    }
  });

  it("locks the shared glossary", () => {
    expect(resources.en.common.terms).toMatchObject({
      agent: "Agent",
      harness: "Harness",
      reasoningEffort: "Reasoning effort",
      token: "Token",
    });
    expect(resources["zh-CN"].common.terms).toMatchObject({
      agent: "智能体",
      harness: "运行框架",
      reasoningEffort: "推理强度",
      token: "Token",
    });
    expect(JSON.stringify(resources["zh-CN"])).not.toContain("令牌");
    expect(resources.en.common.documentTitle).toBe("Omnigent");
    expect(resources["zh-CN"].common.documentTitle).toBe("Omnigent");
  });
});
