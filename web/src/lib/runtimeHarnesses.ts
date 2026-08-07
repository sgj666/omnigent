export type RuntimeKind = "nativeCli" | "sdk" | "api" | "custom";

export interface InstalledRuntime {
  id: string;
  displayName: string;
  kind: RuntimeKind;
  reportedAliases: string[];
}

interface RuntimeDefinition {
  id: string;
  displayName: string;
  kind: RuntimeKind;
  aliases: readonly string[];
}

const RUNTIME_DEFINITIONS: readonly RuntimeDefinition[] = [
  {
    id: "claude-native",
    displayName: "Claude Code",
    kind: "nativeCli",
    aliases: ["claude-native", "native-claude"],
  },
  {
    id: "claude-sdk",
    displayName: "Claude SDK",
    kind: "sdk",
    aliases: ["claude-sdk", "claude_sdk", "claude"],
  },
  {
    id: "codex-native",
    displayName: "Codex CLI",
    kind: "nativeCli",
    aliases: ["codex-native", "native-codex"],
  },
  { id: "codex", displayName: "Codex", kind: "sdk", aliases: ["codex"] },
  {
    id: "openai-agents",
    displayName: "OpenAI Agents",
    kind: "sdk",
    aliases: ["openai-agents", "openai-agents-sdk", "agents_sdk"],
  },
  {
    id: "open-responses",
    displayName: "Open Responses",
    kind: "api",
    aliases: ["open-responses"],
  },
  {
    id: "antigravity",
    displayName: "Antigravity",
    kind: "sdk",
    aliases: ["antigravity", "google-antigravity", "agy"],
  },
  { id: "cursor", displayName: "Cursor", kind: "sdk", aliases: ["cursor"] },
  {
    id: "cursor-native",
    displayName: "Cursor CLI",
    kind: "nativeCli",
    aliases: ["cursor-native", "native-cursor"],
  },
  { id: "pi", displayName: "Pi", kind: "sdk", aliases: ["pi"] },
  {
    id: "pi-native",
    displayName: "Pi CLI",
    kind: "nativeCli",
    aliases: ["pi-native", "native-pi"],
  },
  {
    id: "qwen",
    displayName: "Qwen Code",
    kind: "sdk",
    aliases: ["qwen", "qwen-code"],
  },
  {
    id: "qwen-native",
    displayName: "Qwen CLI",
    kind: "nativeCli",
    aliases: ["qwen-native", "native-qwen"],
  },
  { id: "opencode", displayName: "OpenCode", kind: "sdk", aliases: ["opencode"] },
  {
    id: "opencode-native",
    displayName: "OpenCode CLI",
    kind: "nativeCli",
    aliases: ["opencode-native", "native-opencode"],
  },
  { id: "goose", displayName: "Goose", kind: "sdk", aliases: ["goose"] },
  {
    id: "goose-native",
    displayName: "Goose CLI",
    kind: "nativeCli",
    aliases: ["goose-native", "native-goose"],
  },
  { id: "kimi", displayName: "Kimi", kind: "sdk", aliases: ["kimi", "kimi-code"] },
  {
    id: "kimi-native",
    displayName: "Kimi CLI",
    kind: "nativeCli",
    aliases: ["kimi-native", "native-kimi"],
  },
  { id: "hermes", displayName: "Hermes", kind: "sdk", aliases: ["hermes"] },
  {
    id: "hermes-native",
    displayName: "Hermes CLI",
    kind: "nativeCli",
    aliases: ["hermes-native", "native-hermes"],
  },
  {
    id: "kiro-native",
    displayName: "Kiro",
    kind: "nativeCli",
    aliases: ["kiro-native", "native-kiro"],
  },
  {
    id: "copilot",
    displayName: "GitHub Copilot",
    kind: "sdk",
    aliases: ["copilot", "github-copilot"],
  },
  { id: "acp", displayName: "ACP", kind: "custom", aliases: ["acp"] },
];

const DEFINITION_BY_ALIAS = new Map(
  RUNTIME_DEFINITIONS.flatMap((definition) =>
    definition.aliases.map((alias) => [alias, definition] as const),
  ),
);

/** Collapse readiness aliases and return only runtimes the Host reports as launchable. */
export function installedRuntimes(
  readiness: Record<string, boolean | string> | null | undefined,
): InstalledRuntime[] {
  if (!readiness) return [];
  const readyNames = Object.entries(readiness)
    .filter(([, value]) => value === true)
    .map(([name]) => name);
  const readySet = new Set(readyNames);
  const consumed = new Set<string>();
  const result: InstalledRuntime[] = [];

  for (const definition of RUNTIME_DEFINITIONS) {
    const reportedAliases = definition.aliases.filter((alias) => readySet.has(alias));
    if (reportedAliases.length === 0) continue;
    reportedAliases.forEach((alias) => consumed.add(alias));
    result.push({
      id: definition.id,
      displayName: definition.displayName,
      kind: definition.kind,
      reportedAliases: [...reportedAliases],
    });
  }

  for (const name of readyNames.filter((candidate) => !consumed.has(candidate)).sort()) {
    result.push({ id: name, displayName: name, kind: "custom", reportedAliases: [name] });
  }
  return result;
}

/** Map an Agent harness spelling onto the Runtime card it belongs to. */
export function runtimeIdForHarness(harness: string | null | undefined): string | null {
  if (!harness) return null;
  return DEFINITION_BY_ALIAS.get(harness)?.id ?? harness;
}
