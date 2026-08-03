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

  it("keeps ChatPage status and context feedback professionally localized", () => {
    expect(resources["zh-CN"].chat).toMatchObject({
      loadingConversation: "正在加载会话…",
      conversationLoadFailed: "无法加载",
      startNewChat: "开始新聊天",
      jumpToFirstMessage: "跳转到第一条消息",
      planMode: "规划模式",
      contextUsed: "已使用上下文的 {{percent}}%",
      contextUsage: "{{used}} / {{limit}} Token（{{percent}}%）",
      contextWindowUnknown: "（上下文窗口大小未知）",
      contextUsageUnavailable: "暂无用量数据 — 发送一条消息后即可查看。",
      contextItems: "上下文中的条目：{{count}}",
      unknownCommand: "未知命令：{{command}}。可用命令：{{available}}",
      closedSubAgent: "此子智能体会话已关闭",
      readOnlySubAgent: "Claude Code 子智能体为只读",
      subAgentDefault: "子智能体",
      mcpMoreNames: "还有 {{count}} 个",
      unknownError: "未知错误",
      commandModelDefault: "智能体默认模型",
    });
    expect(resources["zh-CN"].chat.contextModel).toContain("{{model}}");
    expect(resources["zh-CN"].chat.contextModelOverride).toContain("{{model}}");
  });
});
