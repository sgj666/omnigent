import { describe, expect, it } from "vitest";
import { installedRuntimes, runtimeIdForHarness } from "./runtimeHarnesses";

describe("installedRuntimes", () => {
  it("keeps only ready runtimes and collapses aliases", () => {
    expect(
      installedRuntimes({
        claude: true,
        claude_sdk: true,
        "claude-sdk": true,
        "claude-native": true,
        "native-claude": true,
        "codex-native": "binary-missing",
        cursor: false,
      }),
    ).toEqual([
      {
        id: "claude-native",
        displayName: "Claude Code",
        kind: "nativeCli",
        reportedAliases: ["claude-native", "native-claude"],
      },
      {
        id: "claude-sdk",
        displayName: "Claude SDK",
        kind: "sdk",
        reportedAliases: ["claude-sdk", "claude_sdk", "claude"],
      },
    ]);
  });

  it("preserves a ready plugin runtime it does not know yet", () => {
    expect(installedRuntimes({ "company-runtime": true })).toEqual([
      {
        id: "company-runtime",
        displayName: "company-runtime",
        kind: "custom",
        reportedAliases: ["company-runtime"],
      },
    ]);
  });
});

describe("runtimeIdForHarness", () => {
  it("maps agent aliases to the same runtime identity", () => {
    expect(runtimeIdForHarness("claude")).toBe("claude-sdk");
    expect(runtimeIdForHarness("agents_sdk")).toBe("openai-agents");
    expect(runtimeIdForHarness("native-qwen")).toBe("qwen-native");
  });
});
