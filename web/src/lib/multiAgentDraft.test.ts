import { describe, expect, it } from "vitest";
import { buildConfigPatches, readAgentConfig, type AgentConfigDraft } from "./multiAgentDraft";

describe("multi-agent visual draft patches", () => {
  it("omits a blank model and only patches changed known fields", () => {
    const original = {
      name: "coordinator",
      executor: { model: "pinned-model", config: { harness: "codex-native" } },
      unknown: { keep: true },
    };
    const visual: AgentConfigDraft = {
      ...readAgentConfig(original),
      description: "Updated",
      model: "",
    };

    expect(buildConfigPatches("config.yaml", original, visual)).toEqual([
      { file: "config.yaml", op: "add", path: "/description", value: "Updated" },
      { file: "config.yaml", op: "remove", path: "/executor/model" },
    ]);
  });

  it("does not rebuild unknown YAML data when nothing visible changed", () => {
    const original = {
      name: "coordinator",
      unknown: { nested: [1, 2, 3] },
      tools: { agents: ["reviewer"] },
    };

    expect(buildConfigPatches("config.yaml", original, readAgentConfig(original))).toEqual([]);
  });
});
