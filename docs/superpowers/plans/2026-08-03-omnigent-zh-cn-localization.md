# Omnigent Simplified Chinese Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add complete, professional English/Simplified Chinese localization to Omnigent's shared UI, including an immediate and persistent system/English/Chinese language setting and localized Electron update dialogs.

**Architecture:** A synchronous bundled `i18next` runtime resolves a small local preference module before first render, while `react-i18next` re-renders mounted UI on changes. Domain JSON resources keep English and Chinese keys in parity; Electron receives the selected preference/effective locale through a narrow preload IPC bridge and owns a small CommonJS resource table for native update dialogs.

**Tech Stack:** React 18, TypeScript 6, Vite 8, Vitest 4, Testing Library, i18next, react-i18next, Electron CommonJS, Node's built-in test runner, pnpm 11.

---

## Working conventions

- Work only in `/Users/zzzz/Documents/multi-agent/omnigent/.worktrees/zh-cn-localization` on `feat/zh-cn-localization`.
- Use the user's local Node 22 runtime (`nvm use 22`) before pnpm commands.
- Preserve raw model IDs, agent/skill/MCP names, paths, commands, terminal output, logs, and server error detail.
- Use the approved glossary in `docs/superpowers/specs/2026-08-03-omnigent-zh-cn-localization-design.md`.
- For each behavior, observe the RED failure before writing production code.
- Run the focused test after GREEN, then the affected domain test group before each commit.

## File structure

### New localization core

- `web/src/i18n/languagePreferences.ts` — preference type, safe storage, system-locale resolution.
- `web/src/i18n/languagePreferences.test.ts` — pure preference behavior.
- `web/src/i18n/index.ts` — synchronous i18next initialization, preference application, DOM/native synchronization, system listener.
- `web/src/i18n/index.test.ts` — runtime change and side-effect behavior.
- `web/src/i18n/resources.ts` — imports and registers every resource namespace.
- `web/src/i18n/resources.test.ts` — key, interpolation, emptiness, and glossary validation.
- `web/src/i18n/testHelpers.ts` — explicit language setup for component tests that exercise Chinese.
- `web/src/i18n/locales/{en,zh-CN}/{common,chat,agents,models,tools,workspace,tasks,settings,account,admin,updates}.json` — bundled domain copy.

### New Electron localization core

- `web/electron/src/desktop_locale.js` — normalize/persist locale and format native update-dialog copy.
- `web/electron/test/desktop_locale.test.js` — CommonJS unit coverage for locale normalization and native strings.

### Existing integration points

- `web/src/main.tsx`, `web/src/embed.tsx`, `web/src/update-overlay.tsx` — initialize the resolved locale before localized rendering.
- `web/src/lib/nativeBridge.ts`, `web/electron/src/preload.js`, `web/electron/src/main.js`, `web/electron/src/update_overlay.js`, `web/electron/src/desktop_updater.js` — renderer-to-main locale sync and native copy.
- `web/src/pages/SettingsPage.tsx`, `web/src/shell/settingsNav.tsx` — the new Language section.
- Existing product components listed in Tasks 5–10 — replace user-visible literals with domain translation keys without unrelated refactors.

## Task 1: Language preference model

**Files:**
- Create: `web/src/i18n/languagePreferences.test.ts`
- Create: `web/src/i18n/languagePreferences.ts`

- [ ] **Step 1: Write the failing preference tests**

```ts
import { describe, expect, it } from "vitest";
import {
  LANGUAGE_PREFERENCE_KEY,
  readLanguagePreference,
  resolveLanguage,
  resolveSystemLanguage,
  writeLanguagePreference,
} from "./languagePreferences";

describe("language preferences", () => {
  it.each(["zh", "zh-CN", "zh-SG", "zh-TW"])("maps %s to Simplified Chinese", (tag) => {
    expect(resolveSystemLanguage([tag])).toBe("zh-CN");
  });

  it("falls back to English for unsupported system locales", () => {
    expect(resolveSystemLanguage(["fr-FR", "en-US"])).toBe("en");
  });

  it("treats missing and invalid stored values as system", () => {
    const storage = new Map<string, string>();
    expect(readLanguagePreference({ getItem: (key) => storage.get(key) ?? null })).toBe("system");
    storage.set(LANGUAGE_PREFERENCE_KEY, "de");
    expect(readLanguagePreference({ getItem: (key) => storage.get(key) ?? null })).toBe("system");
  });

  it("persists supported choices and resolves explicit choices", () => {
    const storage = new Map<string, string>();
    writeLanguagePreference("zh-CN", { setItem: (key, value) => storage.set(key, value) });
    expect(storage.get(LANGUAGE_PREFERENCE_KEY)).toBe("zh-CN");
    expect(resolveLanguage("en", ["zh-CN"])).toBe("en");
    expect(resolveLanguage("system", ["zh-CN"])).toBe("zh-CN");
  });
});
```

- [ ] **Step 2: Run the test and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/i18n/languagePreferences.test.ts`

Expected: FAIL because `./languagePreferences` does not exist.

- [ ] **Step 3: Implement the minimal preference module**

```ts
export const LANGUAGE_PREFERENCE_KEY = "omnigent:language";

export type LanguagePreference = "system" | "en" | "zh-CN";
export type SupportedLanguage = Exclude<LanguagePreference, "system">;

type ReadableStorage = Pick<Storage, "getItem">;
type WritableStorage = Pick<Storage, "setItem">;

export function resolveSystemLanguage(languages: readonly string[]): SupportedLanguage {
  return languages.some((tag) => tag.toLowerCase().startsWith("zh")) ? "zh-CN" : "en";
}

export function resolveLanguage(
  preference: LanguagePreference,
  languages: readonly string[],
): SupportedLanguage {
  return preference === "system" ? resolveSystemLanguage(languages) : preference;
}

export function readLanguagePreference(storage: ReadableStorage): LanguagePreference {
  try {
    const value = storage.getItem(LANGUAGE_PREFERENCE_KEY);
    return value === "en" || value === "zh-CN" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

export function writeLanguagePreference(
  preference: LanguagePreference,
  storage: WritableStorage,
): void {
  try {
    storage.setItem(LANGUAGE_PREFERENCE_KEY, preference);
  } catch {
    // Persistence is optional; the in-memory language still changes.
  }
}
```

- [ ] **Step 4: Run focused and full preference tests**

Run: `nvm use 22 && pnpm --filter web test -- src/i18n/languagePreferences.test.ts`

Expected: PASS, 4 test groups with all parameterized cases green.

- [ ] **Step 5: Commit**

```bash
git add web/src/i18n/languagePreferences.ts web/src/i18n/languagePreferences.test.ts
git commit -m "feat(web): add language preference model"
```

## Task 2: Bundled i18next runtime and resource contract

**Files:**
- Modify: `web/package.json`
- Modify: `pnpm-lock.yaml`
- Create: `web/src/i18n/index.ts`
- Create: `web/src/i18n/index.test.ts`
- Create: `web/src/i18n/resources.ts`
- Create: `web/src/i18n/resources.test.ts`
- Create: `web/src/i18n/testHelpers.ts`
- Create: `web/src/i18n/locales/en/common.json`
- Create: `web/src/i18n/locales/zh-CN/common.json`
- Create: `web/src/i18n/locales/en/chat.json`
- Create: `web/src/i18n/locales/zh-CN/chat.json`
- Create: `web/src/i18n/locales/en/agents.json`
- Create: `web/src/i18n/locales/zh-CN/agents.json`
- Create: `web/src/i18n/locales/en/models.json`
- Create: `web/src/i18n/locales/zh-CN/models.json`
- Create: `web/src/i18n/locales/en/tools.json`
- Create: `web/src/i18n/locales/zh-CN/tools.json`
- Create: `web/src/i18n/locales/en/workspace.json`
- Create: `web/src/i18n/locales/zh-CN/workspace.json`
- Create: `web/src/i18n/locales/en/tasks.json`
- Create: `web/src/i18n/locales/zh-CN/tasks.json`
- Create: `web/src/i18n/locales/en/settings.json`
- Create: `web/src/i18n/locales/zh-CN/settings.json`
- Create: `web/src/i18n/locales/en/account.json`
- Create: `web/src/i18n/locales/zh-CN/account.json`
- Create: `web/src/i18n/locales/en/admin.json`
- Create: `web/src/i18n/locales/zh-CN/admin.json`
- Create: `web/src/i18n/locales/en/updates.json`
- Create: `web/src/i18n/locales/zh-CN/updates.json`
- Modify: `web/src/main.tsx`
- Modify: `web/src/embed.tsx`

- [ ] **Step 1: Write RED tests for resource parity and runtime behavior**

```ts
// resources.test.ts
import { describe, expect, it } from "vitest";
import { resources } from "./resources";

function interpolationKeys(value: string): string[] {
  return [...value.matchAll(/{{\s*([^},\s]+)[^}]*}}/g)].map((match) => match[1]).sort();
}

function walk(value: unknown, prefix = ""): Map<string, string> {
  const result = new Map<string, string>();
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof child === "string") result.set(path, child);
    else walk(child, path).forEach((text, nested) => result.set(nested, text));
  }
  return result;
}

describe("translation resources", () => {
  it("keeps English and Chinese keys and interpolation variables identical", () => {
    const englishNamespaces = resources.en as Record<string, unknown>;
    const chineseNamespaces = resources["zh-CN"] as Record<string, unknown>;
    for (const namespace of Object.keys(englishNamespaces)) {
      const english = walk(englishNamespaces[namespace]);
      const chinese = walk(chineseNamespaces[namespace]);
      expect([...chinese.keys()].sort()).toEqual([...english.keys()].sort());
      for (const [key, value] of english) {
        expect(chinese.get(key)?.trim()).not.toBe("");
        expect(interpolationKeys(chinese.get(key) ?? "")).toEqual(interpolationKeys(value));
      }
    }
  });

  it("locks approved AI terminology", () => {
    expect(resources["zh-CN"].common.terms.agent).toBe("智能体");
    expect(resources["zh-CN"].common.terms.harness).toBe("运行框架");
    expect(resources["zh-CN"].common.terms.reasoningEffort).toBe("推理强度");
    expect(JSON.stringify(resources["zh-CN"])).not.toContain("令牌");
  });
});
```

```ts
// index.test.ts
it("applies a manual language immediately and synchronizes the document", async () => {
  await setUiLanguagePreference("zh-CN");
  expect(i18n.resolvedLanguage).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");
});

it("re-resolves a system preference on languagechange", async () => {
  await setUiLanguagePreference("system");
  setNavigatorLanguages(["zh-CN"]);
  window.dispatchEvent(new Event("languagechange"));
  expect(i18n.resolvedLanguage).toBe("zh-CN");
});
```

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/i18n/resources.test.ts src/i18n/index.test.ts`

Expected: FAIL because the runtime, resources, and i18next packages are absent.

- [ ] **Step 3: Add dependencies and synchronous bundled resources**

Run: `nvm use 22 && pnpm --filter web add i18next react-i18next`

Seed every namespace with a real `meta` label so parity tests operate before domain migration. The common resource must begin with:

```json
{
  "meta": { "languageName": "English" },
  "terms": {
    "agent": "Agent",
    "harness": "Harness",
    "reasoningEffort": "Reasoning effort",
    "token": "Token"
  },
  "documentTitle": "Omnigent"
}
```

```json
{
  "meta": { "languageName": "简体中文" },
  "terms": {
    "agent": "智能体",
    "harness": "运行框架",
    "reasoningEffort": "推理强度",
    "token": "Token"
  },
  "documentTitle": "Omnigent"
}
```

- [ ] **Step 4: Implement the runtime and entry initialization**

`web/src/i18n/index.ts` must expose one initialized instance and one mutation path:

```ts
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import { setDesktopLanguage } from "@/lib/nativeBridge";
import {
  readLanguagePreference,
  resolveLanguage,
  writeLanguagePreference,
  type LanguagePreference,
} from "./languagePreferences";
import { resources } from "./resources";

export const i18n = i18next.createInstance();
let preference: LanguagePreference = readLanguagePreference(window.localStorage);

function browserLanguages(): readonly string[] {
  return navigator.languages.length > 0 ? navigator.languages : [navigator.language];
}

function applyDocumentLanguage(language: "en" | "zh-CN"): void {
  document.documentElement.lang = language;
  document.title = i18n.t("common:documentTitle");
  setDesktopLanguage(preference, language);
}

void i18n.use(initReactI18next).init({
  resources,
  lng: resolveLanguage(preference, browserLanguages()),
  fallbackLng: "en",
  defaultNS: "common",
  initImmediate: false,
  interpolation: { escapeValue: false },
});
applyDocumentLanguage(i18n.resolvedLanguage === "zh-CN" ? "zh-CN" : "en");

export async function setUiLanguagePreference(next: LanguagePreference): Promise<void> {
  preference = next;
  writeLanguagePreference(next, window.localStorage);
  const language = resolveLanguage(next, browserLanguages());
  await i18n.changeLanguage(language);
  applyDocumentLanguage(language);
}

window.addEventListener("languagechange", () => {
  if (preference === "system") void setUiLanguagePreference("system");
});
```

Import `@/i18n` before rendering in `main.tsx` and `embed.tsx`. `testHelpers.ts` exposes `setTestLanguage(language)` and restores English in a returned cleanup callback; component tests opt into Chinese explicitly rather than changing all existing English expectations.

- [ ] **Step 5: Run focused tests, type-check, and commit**

Run: `nvm use 22 && pnpm --filter web test -- src/i18n && pnpm --filter web type-check`

Expected: resource/runtime tests PASS and TypeScript exits 0.

```bash
git add web/package.json pnpm-lock.yaml web/src/i18n web/src/main.tsx web/src/embed.tsx
git commit -m "feat(web): initialize bundled English and Chinese resources"
```

## Task 3: Language setting and immediate switching

**Files:**
- Modify: `web/src/shell/settingsNav.tsx`
- Modify: `web/src/shell/settingsNav.test.tsx`
- Modify: `web/src/pages/SettingsPage.tsx`
- Modify: `web/src/pages/SettingsPage.test.tsx`
- Modify: `web/src/i18n/locales/en/settings.json`
- Modify: `web/src/i18n/locales/zh-CN/settings.json`
- Modify: `web/src/i18n/locales/en/common.json`
- Modify: `web/src/i18n/locales/zh-CN/common.json`

- [ ] **Step 1: Add RED navigation and interaction tests**

```tsx
it("includes Language directly after Appearance", () => {
  const ids = settingsNavGroups(false, false).flatMap((group) => group.items.map((item) => item.id));
  expect(ids.indexOf("language")).toBe(ids.indexOf("appearance") + 1);
});

it("switches to Simplified Chinese immediately and persists the choice", async () => {
  renderPage("/settings/language");
  fireEvent.click(screen.getByRole("radio", { name: "简体中文" }));
  expect(await screen.findByRole("heading", { name: "语言" })).toBeInTheDocument();
  expect(localStorage.getItem("omnigent:language")).toBe("zh-CN");
  expect(document.documentElement).toHaveAttribute("lang", "zh-CN");
});

it("shows the effective language while following the system", () => {
  renderPage("/settings/language");
  expect(screen.getByText("Currently using: English")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/shell/settingsNav.test.tsx src/pages/SettingsPage.test.tsx`

Expected: FAIL because `language` is not a settings section and no language controls exist.

- [ ] **Step 3: Implement the Language section**

Extend `SettingsSectionId` and `SECTION_IDS` with `language`, add a `LanguagesIcon` nav item after Appearance, and render `LanguageSection`:

```tsx
function LanguageSection() {
  const { t, i18n } = useTranslation("settings");
  const [preference, setPreference] = useState(readLanguagePreference(window.localStorage));
  const options: { value: LanguagePreference; label: string }[] = [
    { value: "system", label: t("language.options.system") },
    { value: "en", label: "English" },
    { value: "zh-CN", label: "简体中文" },
  ];

  const choose = (next: LanguagePreference) => {
    setPreference(next);
    void setUiLanguagePreference(next);
  };

  return (
    <Section title={t("language.title")} description={t("language.description")}>
      <div role="radiogroup" aria-label={t("language.title")} className="grid max-w-xl gap-3">
        {options.map((option) => (
          <button
            type="button"
            role="radio"
            aria-checked={preference === option.value}
            key={option.value}
            onClick={() => choose(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {preference === "system" && (
        <p>{t("language.current", { language: i18n.resolvedLanguage === "zh-CN" ? "简体中文" : "English" })}</p>
      )}
    </Section>
  );
}
```

Use the page's existing selectable-card styling and `SelectedBadge`; do not introduce a second card abstraction.

- [ ] **Step 4: Run focused settings and resource tests**

Run: `nvm use 22 && pnpm --filter web test -- src/shell/settingsNav.test.tsx src/pages/SettingsPage.test.tsx src/i18n/resources.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/shell/settingsNav.tsx web/src/shell/settingsNav.test.tsx web/src/pages/SettingsPage.tsx web/src/pages/SettingsPage.test.tsx web/src/i18n/locales
git commit -m "feat(web): add language settings"
```

## Task 4: Electron locale synchronization and native update copy

**Files:**
- Create: `web/electron/src/desktop_locale.js`
- Create: `web/electron/test/desktop_locale.test.js`
- Modify: `web/src/lib/nativeBridge.ts`
- Modify: `web/src/lib/nativeBridge.test.ts`
- Modify: `web/electron/src/preload.js`
- Modify: `web/electron/src/main.js`
- Modify: `web/electron/src/desktop_updater.js`
- Modify: `web/electron/test/desktop_updater.test.js`
- Modify: `web/electron/src/update_overlay.js`
- Modify: `web/electron/test/update-main.test.js`
- Modify: `web/src/update-overlay.tsx`

- [ ] **Step 1: Write RED tests for normalization, IPC, and dialog copy**

```js
const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { normalizeDesktopLanguage, nativeUpdateCopy } = require("../src/desktop_locale");

describe("desktop locale", () => {
  it("resolves system Chinese and rejects invalid persisted values", () => {
    assert.equal(normalizeDesktopLanguage({ ui_language: "system" }, "zh-TW"), "zh-CN");
    assert.equal(normalizeDesktopLanguage({ ui_language: "de" }, "fr-FR"), "en");
  });

  it("formats trusted-host update approval in Chinese", () => {
    const copy = nativeUpdateCopy("zh-CN", "download", { host: "localhost:6767" });
    assert.equal(copy.message, "下载 Omnigent 更新？");
    assert.match(copy.detail, /localhost:6767/);
    assert.deepEqual(copy.buttons, ["不允许", "仅允许一次"]);
  });
});
```

Add renderer tests asserting `setDesktopLanguage("system", "zh-CN")` calls the optional Electron bridge and returns false in a browser. Extend updater tests so `confirmControl` selects Chinese copy when `getLocale()` returns `zh-CN`.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --dir web/electron test -- test/desktop_locale.test.js test/desktop_updater.test.js && pnpm --filter web test -- src/lib/nativeBridge.test.ts`

Expected: FAIL because the desktop locale module and bridge method do not exist.

- [ ] **Step 3: Implement the narrow bridge and native resource table**

`desktop_locale.js` owns only `en` and `zh-CN`, returns English for unknown locales, and interpolates the already-validated host. Add this optional API:

```ts
interface ElectronDesktopApi extends NativeShellApi {
  kind: "electron";
  setLanguage?: (preference: LanguagePreference, effectiveLanguage: SupportedLanguage) => void;
}

export function setDesktopLanguage(
  preference: LanguagePreference,
  effectiveLanguage: SupportedLanguage,
): boolean {
  const api = electronApi();
  if (!api?.setLanguage) return false;
  try {
    api.setLanguage(preference, effectiveLanguage);
    return true;
  } catch (error) {
    console.warn("[nativeBridge] setLanguage failed:", error);
    return false;
  }
}
```

The preload sends `omnigent:set-language`. Main validates the sender with `isPinnedOriginSender`, accepts only `system`, `en`, or `zh-CN` plus effective `en`/`zh-CN`, saves `ui_language` and `ui_locale`, and tells the update overlay to reload its query locale. Pass `getLocale` into `createDesktopUpdater`; replace only its user-visible native dialog copy, leaving thrown diagnostic strings English/verbatim.

`update_overlay.js` appends `locale=<effective>` to the overlay URL. `update-overlay.tsx` reads that query value, applies it to the shared i18n instance before `createRoot`, and sets `<html lang>`.

- [ ] **Step 4: Run web/Electron focused tests**

Run: `nvm use 22 && pnpm --dir web/electron test -- test/desktop_locale.test.js test/desktop_updater.test.js test/update-main.test.js && pnpm --filter web test -- src/lib/nativeBridge.test.ts src/i18n/index.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/electron/src web/electron/test web/src/lib/nativeBridge.ts web/src/lib/nativeBridge.test.ts web/src/update-overlay.tsx
git commit -m "feat(electron): localize native update controls"
```

## Task 5: Shell navigation and session-management localization

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/shell/AppShell.tsx`
- Modify: `web/src/shell/Sidebar.tsx`
- Modify: `web/src/shell/sidebarNav.ts`
- Modify: `web/src/shell/settingsNav.tsx`
- Modify: `web/src/shell/ChatHeader.tsx`
- Modify: `web/src/shell/CommandPalette.tsx`
- Modify: `web/src/shell/SessionRail.tsx`
- Modify: `web/src/shell/TitleBarServerPicker.tsx`
- Modify: `web/src/shell/NewChatDialog.tsx`
- Modify: `web/src/shell/NewProjectButton.tsx`
- Modify: `web/src/shell/ForkSessionDialog.tsx`
- Modify: `web/src/shell/ReconnectSessionDialog.tsx`
- Modify: `web/src/shell/ResumeWithDirectoryDialog.tsx`
- Modify: `web/src/shell/ProjectSettingsDialog.tsx`
- Modify the corresponding existing `*.test.tsx` and `sidebarNav.test.ts` files.
- Modify: `web/src/i18n/locales/{en,zh-CN}/common.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/chat.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/workspace.json`

- [ ] **Step 1: Add one Chinese shell-flow test before migration**

In `Sidebar.test.tsx`, render after `setTestLanguage("zh-CN")` and assert the primary actions “新建会话”, “设置”, “归档” and the search placeholder. In `NewChatDialog.test.tsx`, assert “新建会话”, “工作区”, “创建” and the validation copy while preserving a model ID fixture verbatim.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/shell/Sidebar.test.tsx src/shell/NewChatDialog.test.tsx`

Expected: FAIL on the first Chinese role/text query.

- [ ] **Step 3: Migrate the listed shell files**

Use complete sentence keys rather than fragments. The shell resource shape starts with:

```json
{
  "sidebar": {
    "newSession": "New session",
    "searchSessions": "Search sessions",
    "settings": "Settings",
    "archived": "Archived",
    "untitledSession": "New session"
  },
  "sessionActions": {
    "archive": "Archive session",
    "unarchive": "Unarchive session",
    "delete": "Delete session",
    "fork": "Fork from here",
    "reconnect": "Reconnect session"
  }
}
```

The Chinese resource uses “新建会话”, “搜索会话”, “设置”, “已归档”, “归档会话”, “取消归档”, “删除会话”, “从此处创建分支会话”, and “重新连接会话”. Preserve project names, session titles, server origins, branch names, and shortcuts through interpolation.

- [ ] **Step 4: Run shell tests and resource validation**

Run: `nvm use 22 && pnpm --filter web test -- src/shell src/i18n/resources.test.ts`

Expected: all shell and resource tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/shell web/src/i18n/locales
git commit -m "feat(web): localize navigation and session management"
```

## Task 6: Chat, composer, status, and conversation-block localization

**Files:**
- Modify: `web/src/pages/ChatPage.tsx`
- Modify: `web/src/pages/QueuedMessagesStrip.tsx`
- Modify: `web/src/pages/TurnRail.tsx`
- Modify: `web/src/components/ComposerMicButton.tsx`
- Modify: `web/src/components/FileMentionMenu.tsx`
- Modify: `web/src/components/HostBadge.tsx`
- Modify: `web/src/components/KeyboardShortcutsDialog.tsx`
- Modify: `web/src/components/SessionStateBadge.tsx`
- Modify: `web/src/components/SlashCommandMenu.tsx`
- Modify: `web/src/components/UserMessageNav.tsx`
- Modify: `web/src/components/ai-elements/conversation.tsx`
- Modify: `web/src/components/ai-elements/message.tsx`
- Modify: `web/src/components/ai-elements/reasoning.tsx`
- Modify: `web/src/components/blocks/ApprovalCard.tsx`
- Modify: `web/src/components/blocks/AskUserQuestionForm.tsx`
- Modify: `web/src/components/blocks/BlockRenderer.tsx`
- Modify: `web/src/components/blocks/ExitPlanModeReview.tsx`
- Modify: `web/src/components/blocks/ReasoningView.tsx`
- Modify: `web/src/components/blocks/SlashCommandCard.tsx`
- Modify: `web/src/components/blocks/SmartRoutingCard.tsx`
- Modify: `web/src/components/blocks/StatusBlocks.tsx`
- Modify: `web/src/components/blocks/SystemMessage.tsx`
- Modify: `web/src/components/blocks/TerminalCommandCard.tsx`
- Modify: `web/src/components/blocks/ToolCard.tsx`
- Modify: `web/src/components/goal/CommandGoalDialog.tsx`
- Modify: `web/src/components/goal/GoalControl.tsx`
- Modify: `web/src/components/goal/GoalDialog.tsx`
- Modify: `web/src/components/goal/goalUtils.ts`
- Modify affected tests beside these files, especially `ChatPage.composer.test.tsx`, `ChatPage.indicators.test.tsx`, `PermissionsModal.test.tsx`, and block tests.
- Modify: `web/src/i18n/locales/{en,zh-CN}/chat.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/tools.json`

- [ ] **Step 1: Add RED Chinese critical-path tests**

Assert in Chinese mode:

```tsx
expect(screen.getByRole("textbox", { name: "向智能体发送消息" })).toHaveAttribute(
  "placeholder",
  "询问智能体任何问题…",
);
expect(screen.getByLabelText("中断")).toBeInTheDocument();
expect(screen.getByText("处理中…")).toBeInTheDocument();
expect(screen.getByRole("button", { name: "压缩上下文" })).toBeInTheDocument();
```

Add a block test that retains the raw tool name and arguments while translating “工具调用”, “批准”, “拒绝”, and “显示详情”.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/pages/ChatPage.composer.test.tsx src/pages/ChatPage.indicators.test.tsx src/components/blocks`

Expected: FAIL on Chinese UI copy while raw tool fixture assertions remain green.

- [ ] **Step 3: Migrate chat copy with professional terminology**

Move working-message rotation, sandbox startup stages, MCP startup sentences, slash-command help/errors, composer placeholders, session status, queue copy, context usage, Plan mode, copy/reply/fork actions, approval labels, and goal controls to `chat` or `tools` keys. Preserve raw errors as `t("errors.operationFailed", { detail: error.message })` where the translation explicitly includes the detail.

Use plural keys for counts:

```json
{
  "backgroundTasks_one": "{{count}} background task is still running",
  "backgroundTasks_other": "{{count}} background tasks are still running",
  "contextItems_one": "{{count}} item in context",
  "contextItems_other": "{{count}} items in context"
}
```

```json
{
  "backgroundTasks_one": "仍有 {{count}} 个后台任务正在运行",
  "backgroundTasks_other": "仍有 {{count}} 个后台任务正在运行",
  "contextItems_one": "上下文中有 {{count}} 项内容",
  "contextItems_other": "上下文中有 {{count}} 项内容"
}
```

- [ ] **Step 4: Run chat/block tests and type-check**

Run: `nvm use 22 && pnpm --filter web test -- src/pages/ChatPage src/components/blocks src/components/goal src/i18n/resources.test.ts && pnpm --filter web type-check`

Expected: PASS and TypeScript exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/ChatPage* web/src/pages/QueuedMessagesStrip.tsx web/src/pages/TurnRail* web/src/components web/src/i18n/locales
git commit -m "feat(web): localize chat and agent activity"
```

## Task 7: Agent, harness, model, and approval configuration localization

**Files:**
- Modify: `web/src/components/AgentCard.tsx`
- Modify: `web/src/components/AgentHoverCard.tsx`
- Modify: `web/src/components/AgentInfo.tsx`
- Modify: `web/src/components/CostRoutingControl.tsx`
- Modify: `web/src/components/HarnessConfigControls.tsx`
- Modify: `web/src/components/ModelValueCombobox.tsx`
- Modify: `web/src/components/PermissionsModal.tsx`
- Modify: `web/src/components/PresenceAvatars.tsx`
- Modify: `web/src/components/SkillPills.tsx`
- Modify: `web/src/shell/AddAgentDialog.tsx`
- Modify: `web/src/shell/CreateAgentDialog.tsx`
- Modify: `web/src/shell/SwitchAgentDialog.tsx`
- Modify: `web/src/shell/HarnessCredentialForm.tsx`
- Modify: `web/src/shell/HarnessSetupDialog.tsx`
- Modify: `web/src/shell/SubagentsGraphView.tsx`
- Modify: `web/src/shell/SubagentsPanel.tsx`
- Modify affected adjacent tests.
- Modify: `web/src/i18n/locales/{en,zh-CN}/agents.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/models.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/tools.json`

- [ ] **Step 1: Add RED terminology and preservation tests**

Render `CreateAgentDialog` and `PermissionsModal` in Chinese. Assert “创建智能体”, “运行框架”, “模型”, “推理强度”, “智能路由”, “审批请求”, “批准并继续”, and “拒绝”; assert the fixtures `codex-native`, `gpt-5.4`, `filesystem.read`, and `/workspace/app.ts` remain unchanged.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/shell/CreateAgentDialog.test.tsx src/components/PermissionsModal.test.tsx`

Expected: FAIL on Chinese labels only.

- [ ] **Step 3: Migrate the listed configuration surfaces**

Use “智能体” for the product concept and “运行框架” for harness labels/descriptions. Keep harness IDs and provider/model values raw. Translate low/medium/high effort display labels as “低 / 中 / 高”, while values sent to APIs remain `low`, `medium`, `high`. Translate permission policy explanations and action outcomes, not tool input payloads.

- [ ] **Step 4: Run agent/model/permission tests**

Run: `nvm use 22 && pnpm --filter web test -- src/components/Agent src/components/Harness src/components/Model src/components/PermissionsModal src/shell/AddAgentDialog src/shell/CreateAgentDialog src/shell/SwitchAgentDialog src/shell/Harness src/shell/Subagents src/i18n/resources.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components web/src/shell web/src/i18n/locales
git commit -m "feat(web): localize agent and model controls"
```

## Task 8: Workspace, files, browser, and terminal-chrome localization

**Files:**
- Modify: `web/src/components/BrowserPane/BrowserPane.tsx`
- Modify: `web/src/components/ImageLightbox.tsx`
- Modify: `web/src/components/SessionImage.tsx`
- Modify: `web/src/shell/CliCommandBlock.tsx`
- Modify: `web/src/shell/CodeViewer.tsx`
- Modify: `web/src/shell/ExecutionLogsPanel.tsx`
- Modify: `web/src/shell/FileDownloadButton.tsx`
- Modify: `web/src/shell/FileViewer.tsx`
- Modify: `web/src/shell/FilesPanel.tsx`
- Modify: `web/src/shell/FilesPanelDrawer.tsx`
- Modify: `web/src/shell/FlatFileList.tsx`
- Modify: `web/src/shell/FolderTree.tsx`
- Modify: `web/src/shell/HtmlCommentViewer.tsx`
- Modify: `web/src/shell/InlineTerminalsSection.tsx`
- Modify: `web/src/shell/MainTerminalView.tsx`
- Modify: `web/src/shell/MarkdownEditorToolbar.tsx`
- Modify: `web/src/shell/MarkdownSearchBar.tsx`
- Modify: `web/src/shell/MobilePanelDrawer.tsx`
- Modify: `web/src/shell/ModelViewer.tsx`
- Modify: `web/src/shell/NewTerminalButton.tsx`
- Modify: `web/src/shell/NotebookPreview.tsx`
- Modify: `web/src/shell/PdfViewer.tsx`
- Modify: `web/src/shell/PreviewSearchBar.tsx`
- Modify: `web/src/shell/RunnerAsleepHint.tsx`
- Modify: `web/src/shell/TableBubbleMenu.tsx`
- Modify: `web/src/shell/TerminalsPanel.tsx`
- Modify: `web/src/shell/TodoPanel.tsx`
- Modify: `web/src/shell/TruncatedBanner.tsx`
- Modify: `web/src/shell/WorkspacePanel.tsx`
- Modify: `web/src/shell/WorkspacePathField.tsx`
- Modify: `web/src/shell/WorkspacePicker.tsx`
- Modify: `web/src/shell/terminalStatus.tsx`
- Modify affected adjacent tests.
- Modify: `web/src/i18n/locales/{en,zh-CN}/workspace.json`

- [ ] **Step 1: Add RED Chinese workspace/terminal tests**

Add Chinese-mode assertions to `FilesPanel.test.tsx`, `WorkspacePicker.test.tsx`, `NewTerminalButton.test.tsx`, and `MainTerminalView.test.tsx` for “文件”, “工作区”, “选择文件夹”, “新建 Shell”, “关闭 Shell”, “终端正在启动…”, and “重新连接”. Keep fixture paths, filenames, command text, and xterm output unchanged.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/shell/FilesPanel.test.tsx src/shell/WorkspacePicker.test.tsx src/shell/NewTerminalButton.test.tsx src/shell/MainTerminalView.test.tsx`

Expected: FAIL on translated chrome labels; raw fixture assertions remain green.

- [ ] **Step 3: Migrate only chrome and Omnigent-authored status**

Translate file/browser/preview/editor controls, worktree actions, terminal tabs/buttons/status, terminal theme labels, and Omnigent connection guidance. Do not pass terminal payload through `t()`, do not change `LANG`/`LC_*`, and do not translate code, filenames, paths, branch names, command lines, log bodies, or native TUI output.

- [ ] **Step 4: Run workspace and terminal suites**

Run: `nvm use 22 && pnpm --filter web test -- src/components/BrowserPane src/components/ImageLightbox src/components/SessionImage src/shell/CodeViewer src/shell/File src/shell/Files src/shell/FlatFileList src/shell/FolderTree src/shell/HtmlCommentViewer src/shell/MainTerminalView src/shell/Markdown src/shell/NewTerminalButton src/shell/PreviewSearchBar src/shell/Terminal src/shell/TerminalsPanel src/shell/Workspace src/i18n/resources.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components web/src/shell web/src/i18n/locales/en/workspace.json web/src/i18n/locales/zh-CN/workspace.json
git commit -m "feat(web): localize workspace and terminal chrome"
```

## Task 9: Tasks, schedules, inbox, comments, and sharing localization

**Files:**
- Modify: `web/src/pages/InboxPage.tsx`
- Modify: `web/src/pages/TasksPage.tsx`
- Modify: `web/src/components/scheduled/CreateScheduledTaskDialog.tsx`
- Modify: `web/src/components/scheduled/Label.tsx`
- Modify: `web/src/components/scheduled/ModelEffortFields.tsx`
- Modify: `web/src/components/scheduled/ScheduleFields.tsx`
- Modify: `web/src/components/scheduled/ScheduledTaskRow.tsx`
- Modify: `web/src/components/scheduled/suggestions.ts`
- Modify: `web/src/shell/CommentsPanel.tsx`
- Modify: `web/src/pages/SharingPage.tsx`
- Modify: `web/src/lib/scheduleText.ts`
- Modify affected adjacent tests.
- Modify: `web/src/i18n/locales/{en,zh-CN}/tasks.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/common.json`

- [ ] **Step 1: Add RED workflow tests**

In Chinese mode assert “任务”, “新建定时任务”, “收件箱”, “评论”, “共享会话”, localized recurrence summaries, and count-sensitive empty states. Preserve task titles, prompts, usernames, cron/rrule values, and timezone IDs.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/pages/InboxPage.test.tsx src/pages/TasksPage.test.tsx src/components/scheduled src/shell/CommentsPanel.test.tsx src/pages/SharingPage.test.tsx`

Expected: FAIL on Chinese queries.

- [ ] **Step 3: Migrate productivity copy and schedule formatting**

Change schedule helpers to accept a translation function or locale instead of returning fixed English. Use `Intl.DateTimeFormat(effectiveLanguage)` for user-facing dates while keeping IANA timezone names unchanged. Translate workflow actions and permission descriptions; interpolate user-supplied titles/names verbatim.

- [ ] **Step 4: Run productivity tests and resource validation**

Run: `nvm use 22 && pnpm --filter web test -- src/pages/InboxPage src/pages/TasksPage src/pages/SharingPage src/components/scheduled src/shell/CommentsPanel src/lib/scheduleText src/i18n/resources.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages web/src/components/scheduled web/src/shell/CommentsPanel* web/src/lib/scheduleText* web/src/i18n/locales
git commit -m "feat(web): localize tasks and collaboration"
```

## Task 10: Authentication, administration, setup, and remaining settings localization

**Files:**
- Modify: `web/src/pages/ApprovePage.tsx`
- Modify: `web/src/pages/LoginPage.tsx`
- Modify: `web/src/pages/RegisterPage.tsx`
- Modify: `web/src/pages/SetupPage.tsx`
- Modify: `web/src/pages/NotFoundPage.tsx`
- Modify: `web/src/pages/MembersPage.tsx`
- Modify: `web/src/pages/PoliciesPage.tsx`
- Modify: `web/src/pages/SettingsPage.tsx`
- Modify: `web/src/components/theme/ThemeColorPicker.tsx`
- Modify: `web/src/components/UpdateBanner.tsx`
- Modify corresponding existing tests.
- Modify: `web/src/i18n/locales/{en,zh-CN}/account.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/admin.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/settings.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/updates.json`

- [ ] **Step 1: Add RED Chinese page tests**

Add Chinese-mode cases asserting “登录”, “创建账户”, “成员”, “策略”, “外观”, “本地 CLI”, “更新”, “已归档会话”, and destructive confirmation consequences. Preserve email addresses, policy expressions, CLI paths/versions, server origins, and raw errors.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/pages/LoginPage.test.tsx src/pages/RegisterPage.test.tsx src/pages/MembersPage.test.tsx src/pages/PoliciesPage.test.tsx src/pages/SettingsPage.test.tsx`

Expected: FAIL on Chinese page content.

- [ ] **Step 3: Migrate the listed pages and settings sections**

Translate client-authored validation, instructions, section titles, theme/font/update labels, membership and policy controls, account actions, archived-session UI, and local CLI guidance. Keep raw authentication/server error details visible after a localized summary. Preserve “Omnigent”, “CLI”, “Git”, provider names, executable paths, and version strings.

- [ ] **Step 4: Run page/settings tests and type-check**

Run: `nvm use 22 && pnpm --filter web test -- src/pages src/components/theme src/components/UpdateBanner src/i18n/resources.test.ts && pnpm --filter web type-check`

Expected: PASS and TypeScript exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages web/src/components/theme web/src/components/UpdateBanner* web/src/i18n/locales
git commit -m "feat(web): localize settings and administration"
```

## Task 11: Locale-sensitive formatting and update surfaces

**Files:**
- Modify: `web/src/lib/relativeTime.ts`
- Modify: `web/src/lib/relativeTime.test.ts`
- Modify: `web/src/lib/timezones.ts`
- Modify: `web/src/pages/InboxPage.tsx`
- Modify: `web/src/pages/SettingsPage.tsx`
- Modify: `web/src/shell/Sidebar.tsx`
- Modify: `web/src/components/pwa/PWAUpdateBanner.tsx`
- Modify: `web/src/components/pwa/PWAUpdateBanner.test.tsx`
- Modify: `web/src/update-overlay.tsx`
- Modify: `web/src/i18n/locales/{en,zh-CN}/common.json`
- Modify: `web/src/i18n/locales/{en,zh-CN}/updates.json`

- [ ] **Step 1: Add RED formatter/update tests**

```ts
it("formats relative time in Simplified Chinese", () => {
  expect(relativeTime(now - 5 * 60_000, now, "zh-CN")).toBe("5 分钟前");
});

it("keeps English formatting available", () => {
  expect(relativeTime(now - 5 * 60_000, now, "en")).toBe("5m ago");
});
```

Add a PWA banner test for “Omnigent 有新版本可用。” with “重新加载” and “忽略”. Add an update-overlay initialization test or extracted pure helper test asserting query `locale=zh-CN` sets the i18n language before render.

- [ ] **Step 2: Run and observe RED**

Run: `nvm use 22 && pnpm --filter web test -- src/lib/relativeTime.test.ts src/components/pwa`

Expected: FAIL because formatters do not accept a locale and the banner is fixed English.

- [ ] **Step 3: Make formatting language-aware**

Accept `SupportedLanguage` at formatting boundaries and use explicit `Intl.DateTimeFormat` / `Intl.NumberFormat` locale arguments. Keep the existing compact English relative-time shape where tests and UI expect it; provide natural Chinese units through translation keys. Localize PWA/update copy. Keep the single static PWA manifest unchanged: its Omnigent name and install metadata are build metadata, not runtime in-app UI, and one manifest cannot follow a per-user language preference.

- [ ] **Step 4: Run formatter/update tests and production web build**

Run: `nvm use 22 && pnpm --filter web test -- src/lib/relativeTime.test.ts src/components/pwa src/components/UpdateBanner.test.tsx && pnpm --filter web build`

Expected: tests PASS and Vite production build exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib web/src/pages/InboxPage.tsx web/src/pages/SettingsPage.tsx web/src/shell/Sidebar.tsx web/src/components/pwa web/src/components/UpdateBanner* web/src/update-overlay.tsx web/src/i18n/locales
git commit -m "feat(web): localize time and update surfaces"
```

## Task 12: Translation coverage audit and regression closure

**Files:**
- Modify only production files identified by the commands below as containing unlocalized user-visible copy.
- Modify the matching namespace JSON files for every corrected string.
- Modify or add the nearest existing test for each behavior correction.

- [ ] **Step 1: Run exact source audits and capture candidate lists**

Run:

```bash
rg -n --glob '*.tsx' --glob '*.ts' \
  '(aria-label|placeholder|title|description|label)=["'"'][A-Z]|>\s*[A-Z][A-Za-z][^<{]{1,100}\s*<' \
  web/src
rg -n --glob '*.tsx' --glob '*.ts' \
  'toast\(|setError\(|new Error\(|tooltip=|TooltipContent|DialogTitle|DialogDescription' \
  web/src
rg -n --glob '*.js' --glob '*.html' \
  'message: "|detail:|buttons:|aria-label=|placeholder=|>[^<{]*[A-Za-z][^<{]*<' \
  web/electron/src/desktop_updater.js web/electron/src/update_overlay.js
```

Expected: remaining matches consist only of tests/developer diagnostics, technical identifiers/data, native mobile exclusions, or genuine missed UI copy.

- [ ] **Step 2: Write a failing test for each genuine missed UI behavior**

For every genuine miss, add a Chinese-mode assertion to the closest adjacent test and run that exact file. Expected: FAIL on the untranslated literal. Do not add assertions for source comments, console-only diagnostics, raw server errors, code/terminal payloads, IDs, commands, paths, brands, or developer-only fixtures.

- [ ] **Step 3: Replace every genuine miss and re-run its focused test**

Add paired English/Chinese resource keys, replace the literal with `t(...)`, preserve dynamic technical/user data through interpolation, and rerun the exact test until PASS. The audit is complete only when every remaining match has been reviewed against the explicit exclusions in the design spec.

- [ ] **Step 4: Run resource validation, type-check, lint, and full web tests**

Run:

```bash
nvm use 22
pnpm --filter web test -- src/i18n/resources.test.ts
pnpm --filter web type-check
pnpm --filter web lint
pnpm --filter web format:check
pnpm --filter web test
```

Expected: resource validation PASS; type-check/lint/format exit 0; full suite has no unexpected failures relative to the 4823-test baseline.

- [ ] **Step 5: Commit audit corrections**

```bash
git add web/src web/electron/src/desktop_updater.js web/electron/src/update_overlay.js
git commit -m "fix(i18n): close remaining localization gaps"
```

## Task 13: Final build, repository checks, and manual acceptance

**Files:**
- No planned production changes. If verification exposes a defect, return to RED/GREEN in the owning task's test and make a focused corrective commit.

- [ ] **Step 1: Run all automated verification from a clean status**

Run:

```bash
nvm use 22
pnpm --filter web test
pnpm --filter web type-check
pnpm --filter web lint
pnpm --filter web format:check
pnpm --filter web build
pnpm --dir web/electron test
/Users/zzzz/Documents/multi-agent/omnigent/.venv/bin/pre-commit run --all-files
git diff --check
git status --short --branch
```

Expected: every command exits 0 and the worktree is clean.

- [ ] **Step 2: Verify English manually**

Run: `nvm use 22 && pnpm --filter web dev`

With language set to English, verify Settings → Language, new session, model/effort configuration, send/interrupt, tool approval, workspace/files, new Shell, tasks, account/admin pages available in the current deployment, and update UI. Confirm no Chinese copy appears and all dynamic IDs/data remain unchanged.

- [ ] **Step 3: Verify Simplified Chinese manually**

Switch to 简体中文 without reloading. Repeat the same path and confirm immediate whole-page changes, professional glossary usage, no clipped card/button text, sensible Chinese punctuation/wrapping, localized ARIA labels, localized date/number presentation, and unchanged terminal content.

- [ ] **Step 4: Verify persistence and system mode**

Reload with `zh-CN` selected and confirm Chinese remains. Select 跟随系统, change the browser/OS language signal between English and Chinese, dispatch or naturally trigger `languagechange`, and confirm the mounted UI follows it. Select English and confirm later system changes no longer affect the UI.

- [ ] **Step 5: Verify Electron behavior**

Run the repository's Electron development command, select 简体中文 in Settings, trigger/update-test the desktop overlay and privileged update confirmation, and confirm their native copy is Chinese while raw updater errors remain intact. Open a Shell and confirm only Omnigent chrome is Chinese; command output and environment are unchanged.

- [ ] **Step 6: Final requirements review**

Re-read `docs/superpowers/specs/2026-08-03-omnigent-zh-cn-localization-design.md` and check each acceptance criterion against a test result or manual observation from Steps 1–5. Report any unavailable environment-dependent Electron behavior explicitly rather than marking it verified.
