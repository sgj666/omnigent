import { describe, expect, it } from "vitest";
import {
  buildConfigPatches,
  parseAgentYaml,
  readAgentConfig,
  resolvePromptFile,
  type AgentConfigDraft,
} from "./multiAgentDraft";

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

  it("preserves inherited booleans as Default and removes explicit values", () => {
    const original = { name: "coordinator", async: true, timers: false, spawn: true };
    const visual: AgentConfigDraft = {
      ...readAgentConfig(original),
      async: undefined,
      timers: undefined,
      spawn: undefined,
    };

    expect(readAgentConfig({ name: "coordinator" })).toMatchObject({
      async: undefined,
      timers: undefined,
      spawn: undefined,
    });
    expect(buildConfigPatches("config.yaml", original, visual)).toEqual([
      { file: "config.yaml", op: "remove", path: "/async" },
      { file: "config.yaml", op: "remove", path: "/timers" },
      { file: "config.yaml", op: "remove", path: "/spawn" },
    ]);
  });

  it("edits a safe relative instructions reference as its real file", () => {
    const config = { name: "reviewer", instructions: "AGENTS.md" };
    const reference = resolvePromptFile("agents/reviewer/config.yaml", config, [
      { path: "agents/reviewer/AGENTS.md", content: "Original prompt\n" },
    ]);
    expect(reference).toEqual({
      path: "agents/reviewer/AGENTS.md",
      content: "Original prompt\n",
    });

    const visual = { ...readAgentConfig(config, reference?.content), prompt: "Updated prompt\n" };
    expect(
      buildConfigPatches("agents/reviewer/config.yaml", config, visual, { reference }),
    ).toEqual([
      {
        file: "agents/reviewer/AGENTS.md",
        op: "replace_file",
        value: "Updated prompt\n",
      },
    ]);
    expect(resolvePromptFile("config.yaml", { instructions: "../secret" }, [])).toBeNull();
  });

  it("refreshes parsed Visual data and locates invalid Advanced YAML", () => {
    const parsed = parseAgentYaml(
      "name: coordinator\ndescription: from yaml\nasync: false\nextension: keep\n",
    );
    expect(parsed).toEqual({
      data: {
        name: "coordinator",
        description: "from yaml",
        async: false,
        extension: "keep",
      },
      diagnostic: null,
    });
    if (!parsed.data) return;
    const visual = { ...readAgentConfig(parsed.data), description: "visual after yaml" };
    expect(buildConfigPatches("config.yaml", parsed.data, visual)).toEqual([
      {
        file: "config.yaml",
        op: "replace",
        path: "/description",
        value: "visual after yaml",
      },
    ]);

    expect(parseAgentYaml("name: [\n")).toMatchObject({
      data: null,
      diagnostic: { line: 2, column: 1 },
    });
  });

  it("initializes nested schema fields without exposing secrets or replacing owned executor config", () => {
    const original = {
      name: "coordinator",
      executor: {
        type: "provider",
        model: "model-1",
        context_window: 128000,
        auth: "existing-secret",
        config: {
          harness: "codex-native",
          provider_region: "us-east",
          retries: 2,
        },
      },
    };
    const schema = {
      schema_version: "1",
      fields: [
        { path: "/executor/type", secret: false },
        { path: "/executor/context_window", secret: false },
        { path: "/executor/auth", secret: true },
        { path: "/executor/config", secret: false },
      ].map((field) => ({
        ...field,
        type: "string" as const,
        group: "executor",
        required: false,
        translation_key: field.path,
      })),
    };

    const visual = readAgentConfig(original, undefined, schema);

    expect(visual.advanced).toEqual({
      "/executor/type": "provider",
      "/executor/context_window": "128000",
      "/executor/config": '{\n  "provider_region": "us-east",\n  "retries": 2\n}',
    });
    expect(visual.configuredSecrets).toEqual(["/executor/auth"]);
    expect(buildConfigPatches("config.yaml", original, visual)).toEqual([]);

    const changed = {
      ...visual,
      advanced: {
        ...visual.advanced,
        "/executor/context_window": "64000",
        "/executor/config": '{"provider_region":"eu-west","retries":2}',
        "/executor/auth": "replacement-secret",
      },
    };
    expect(buildConfigPatches("config.yaml", original, changed)).toEqual([
      {
        file: "config.yaml",
        op: "replace",
        path: "/executor/context_window",
        value: 64000,
      },
      {
        file: "config.yaml",
        op: "replace",
        path: "/executor/config/provider_region",
        value: "eu-west",
      },
      {
        file: "config.yaml",
        op: "replace",
        path: "/executor/auth",
        value: "replacement-secret",
      },
    ]);
  });

  it("parses the block sequences and quoted scalars used by shipped bundles", () => {
    expect(
      parseAgentYaml(`name: polly
description: "Keep # and: punctuation"
tools:
  agents:
    - codex
    - claude_code
steps:
  - name: review
    enabled: true
guardrails:
  on: [tool_call, "after:step"]
`),
    ).toEqual({
      data: {
        name: "polly",
        description: "Keep # and: punctuation",
        tools: { agents: ["codex", "claude_code"] },
        steps: [{ name: "review", enabled: true }],
        guardrails: { on: ["tool_call", "after:step"] },
      },
      diagnostic: null,
    });
  });

  it("accepts the YAML document marker used by bundle config files", () => {
    expect(
      parseAgentYaml(`---
name: polly
executor:
  config:
    harness: codex-native
extension:
  keep: true
`),
    ).toEqual({
      data: {
        name: "polly",
        executor: { config: { harness: "codex-native" } },
        extension: { keep: true },
      },
      diagnostic: null,
    });
  });

  it("accepts standard anchors, aliases, and tags", () => {
    expect(
      parseAgentYaml(`---
name: polly
defaults: &defaults
  enabled: true
extension:
  <<: *defaults
  inherited: *defaults
tagged: !!str 123
`),
    ).toEqual({
      data: {
        name: "polly",
        defaults: { enabled: true },
        extension: { enabled: true, inherited: { enabled: true } },
        tagged: "123",
      },
      diagnostic: null,
    });
  });
});
