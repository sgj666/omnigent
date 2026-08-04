# Omnigent Simplified Chinese Localization Design

**Date:** 2026-08-03  
**Status:** Approved for implementation planning  
**Base commit:** `a1358eb8` (`feat/feishu-team-harness-design`)

## Summary

Add complete English and Simplified Chinese localization to Omnigent's shared React user interface, with a language setting that supports **Follow system**, **English**, and **Simplified Chinese**. The effective language is resolved before the first render, changes immediately without a reload, and persists locally. The same localization layer serves Electron, Web/PWA, the embedded app, and the WebView content used by mobile shells.

This is product localization, not mechanical word substitution. Chinese copy will use a consistent AI-engineering terminology glossary and natural action-oriented wording. Machine-readable identifiers, user or agent content, source code, terminal output, and diagnostic payloads remain verbatim.

## Goals

- Provide `system`, `en`, and `zh-CN` language preferences in Settings.
- Default new and existing installations without an explicit preference to `system`.
- Resolve Chinese system locales to `zh-CN` and all other system locales to `en`.
- Apply language changes immediately across the mounted application.
- Persist explicit language choices locally.
- Localize the complete user-visible shared React interface, accessibility labels, Electron update UI, and Electron-native update dialogs.
- Keep English behavior and functionality unchanged.
- Use consistent, professional terminology familiar to users of Codex and other AI coding desktop applications.
- Localize locale-sensitive dates, times, numbers, plural forms, and currency display.

## Non-goals

- Translating user messages, agent responses, attachments, source code, terminal/PTY output, logs, stack traces, or raw server error details.
- Translating model IDs, custom agent names, skill names, MCP server names, commands, arguments, file paths, Git refs, or commit hashes.
- Changing `LANG`, `LC_ALL`, or any other environment variable for terminal processes.
- Injecting language instructions into Codex, Claude Code, or other agent prompts.
- Adding Traditional Chinese or languages other than English and Simplified Chinese.
- Adding a translation management service, remote language-pack loading, or machine translation.
- Adding a WebView-to-native locale synchronization protocol for Android or iOS shell-owned Toasts and system prompts. Their shared Web content is localized; their small amount of native-shell copy remains governed by the native shell's current behavior.
- Localizing developer comments, internal names, API fields, database values, or test descriptions.

## Product Behavior

### Language choices

Settings gains a dedicated **Language** section directly after **Appearance**. It presents:

- **Follow system** (`system`)
- **English** (`en`)
- **Simplified Chinese** (`zh-CN`)

When **Follow system** is selected, the UI also shows the currently resolved language. A system locale whose normalized tag begins with `zh` resolves to `zh-CN`; every other locale resolves to `en`. This deliberately treats the two supported UI languages as a binary choice rather than pretending to support locale variants for which no resource exists.

Selecting an option writes the preference and switches the mounted UI immediately. A manual `en` or `zh-CN` choice remains stable when the operating-system language changes. A `system` choice responds to the browser `languagechange` event.

### Startup

The preference and effective locale are resolved before the first React render. Initialization updates i18next and `<html lang>` before application content mounts so the app does not flash English before showing Chinese. Invalid or missing preferences are treated as `system`.

### Persistence

The shared renderer stores the preference in `localStorage` under one Omnigent-owned key. If storage is unavailable, the app continues using the resolved system language for that runtime.

Electron additionally receives the preference and effective locale through the existing renderer/preload/main bridge boundary. The main process persists enough locale state in its existing desktop settings store to localize native update dialogs, including dialogs that may appear before the renderer finishes booting. The browser, PWA, embed, and mobile WebView paths do not require this bridge; bridge calls are safe no-ops when Electron is absent.

The language is a local UI preference. It is not added to sessions, messages, agent specs, or server APIs and is not shared with collaborators.

## Architecture

### Internationalization runtime

Add `i18next` and `react-i18next` to the web package. A single shared initialization module will:

1. Load bundled `en` and `zh-CN` resources.
2. Read and resolve the persisted preference.
3. Initialize i18next with English fallback behavior.
4. Update `<html lang>` and the localized document title.
5. subscribe to effective-language changes and, only for the `system` preference, browser `languagechange` events.

Initialization is imported by both the standalone and embedded entry paths before localized React content renders. There is no network request for translations.

### Resources

Resources are split by product domain so ownership and review remain tractable:

- `common`
- `chat`
- `agents`
- `models`
- `tools`
- `workspace`
- `tasks`
- `settings`
- `account`
- `admin`
- `updates`

English resources are the canonical fallback. Simplified Chinese must have the same namespace/key structure and the same interpolation variables. Resource-validation tests reject missing keys, extra keys, empty translations, and interpolation mismatches.

React components use `useTranslation()`. Non-React formatting helpers accept an effective locale or translation function explicitly where necessary. User-facing static arrays or module-level objects must be created through language-aware functions or inside components so a runtime language change cannot leave stale English labels mounted.

Rich sentences containing links, keycaps, emphasis, or embedded components use structured React translations rather than English-order string concatenation. Dynamic values are interpolated into complete sentences so Chinese word order remains natural.

### Locale-sensitive formatting

Dates, relative times, numbers, counts, currency, and plural forms use the effective locale. Existing calls that intentionally format developer or protocol data remain unchanged. Model pricing values retain their units and precision while their surrounding labels and numeric presentation follow the UI locale.

### Electron localization

The native bridge gains the minimum method needed to synchronize the renderer's selected preference and effective locale. Electron-owned update messages and approval dialogs use a small main-process resource table for the same supported locales. Electron does not import the React translation runtime.

The main process normalizes unknown or unavailable values to English. A bridge failure does not block renderer localization or application startup.

### Error handling

- Missing or invalid stored preference: use `system`.
- Unrecognized system locale: use `en`.
- Inaccessible storage: continue with the effective system locale without persistence.
- Missing Chinese translation: fall back to the corresponding English string and warn in development.
- Electron locale-sync failure: continue; only Electron-native copy may use its prior/default locale.
- Server or tool errors: show a localized title and recovery action while preserving the original error detail verbatim.

Localization must never swallow, rewrite, or machine-translate diagnostic content.

## Localization Coverage

The migration includes every user-visible string and accessibility label in the agreed scope:

- Conversation list, empty states, composer, queued messages, run status, and session actions.
- Agent creation and editing, harness selection, model selection, reasoning effort, smart routing, skills, and sub-agents.
- Tool calls, permission requests, approvals, destructive confirmations, and client-authored error copy.
- Workspace and file controls, code-viewer chrome, Git worktree UI, and terminal chrome.
- Tasks, inbox, comments, sharing, members, policies, account, authentication, setup, and settings pages.
- Command palette, keyboard-shortcut reference, tooltips, toasts, loading states, empty states, ARIA labels, and screen-reader-only text.
- PWA update prompts, the standalone update overlay, page titles, Electron update UI, and Electron-native update confirmation dialogs.

Terminal tabs, menus, buttons, connection status, and Omnigent-authored terminal instructions are localized. PTY data and the UI rendered by Codex, Claude Code, Kiro, shells, Git, tests, or other terminal programs remain byte-for-byte unmodified.

## Terminology Glossary

| English | Simplified Chinese | Notes |
| --- | --- | --- |
| Agent | 智能体 | Never use “代理” for the AI product concept. |
| Sub-agent | 子智能体 | A delegated or collaborating agent. |
| Session / Conversation | 会话 | Use one product term for the same UI object. |
| Harness | 运行框架 | The framework that hosts agent execution. |
| Model | 模型 | Preserve provider and model identifiers. |
| Reasoning effort | 推理强度 | The speed/depth setting. |
| Plan mode | 规划模式 | Planning-before-execution behavior. |
| Prompt | 提示词 | Use “发送消息” when describing the user's UI action. |
| Context window | 上下文窗口 | Keep “Token” as the industry term. |
| Compact context | 压缩上下文 | Summarize context to release capacity. |
| Tool call | 工具调用 | Preserve tool names and arguments. |
| Skill | 技能 | Preserve individual skill names. |
| MCP server | MCP 服务器 | Do not expand or translate MCP. |
| Approval | 审批 | Action buttons may use “批准” and “拒绝”; policies use “审批策略”. |
| Permission | 权限 | Keep distinct from the approval workflow. |
| Sandbox | 沙箱 | Standard AI coding term. |
| Workspace | 工作区 | The active project environment. |
| Git worktree | Git 工作树 | Do not conflate with a general workspace. |
| Fork session | 创建分支会话 | Avoid the opaque literal “分叉”. |
| Turn | 轮次 | One user input and agent-processing cycle. |
| Usage / Cost | 用量 / 费用 | Use “Token 用量” where applicable. |
| Runner | 运行器 | The execution unit hosting a session. |
| Host | 主机 | A local or remote execution host. |
| Archive | 归档 | Keep distinct from deletion. |
| Interrupt | 中断 | Stops the current turn without deleting the session. |

Chinese copy is action-oriented and outcome-specific. Buttons use explicit verbs such as “创建智能体”, “批准并继续”, “中断生成”, and “压缩上下文”. Destructive confirmations state the consequence and whether it is reversible. Empty states and client-authored errors explain the next useful action instead of merely translating a heading.

Brand names and proper nouns—including Omnigent, Codex, Claude Code, OpenCode, and Kiro—remain unchanged.

## Testing Strategy

Implementation follows red-green-refactor for behavior changes.

### Preference tests

- Resolve Chinese system locales to `zh-CN` and other locales to `en`.
- Read and write all three preferences.
- Reject invalid stored values and use `system`.
- React to `languagechange` only while following the system.
- Update `<html lang>`, document title, and the Electron bridge when effective language changes.

### Resource validation

- Require namespace and key parity between English and Chinese.
- Require identical interpolation variable sets.
- Reject empty translations.
- Assert glossary-sensitive core translations to prevent terminology drift such as Agent becoming “代理” or Token becoming “令牌”.

### Component and integration tests

- Show the Language settings navigation item and all three choices.
- Persist the selected preference and switch mounted UI immediately.
- Show the resolved language for **Follow system**.
- Update settings, sidebar, and accessibility text together.
- Exercise Chinese versions of new-session creation, message sending, working status, agent configuration, tool approval, workspace/terminal chrome, and destructive confirmation flows.
- Preserve the existing English behavior and test suite.
- Restore the language after a reload.
- Use the synchronized locale in Electron-native update dialogs.

### Full verification

- Web unit tests.
- Type checking.
- Lint and formatting checks.
- Production web build and relevant Electron build/tests.
- Repository `pre-commit run --all-files` requirement.
- A source audit for remaining user-visible English in `web/src`, the Electron update surface, and the standalone update overlay. Every match is either migrated or explicitly classified as permitted technical/brand data.
- Manual critical-path inspection in English and Simplified Chinese, with attention to clipping, wrapping, interpolation, plurals, accessibility labels, and mixed-language remnants.

## Acceptance Criteria

- Settings offers **Follow system**, **English**, and **Simplified Chinese**.
- With no saved preference, the first rendered language follows the system without a language flash.
- A manual selection persists and does not follow later operating-system changes.
- A `system` selection responds to an operating-system/browser language change.
- Language changes update the mounted UI immediately without reloading, reconnecting, or rebuilding a session.
- `<html lang>`, the document title, locale-sensitive formatting, and Electron-native update copy reflect the effective language.
- All agreed user-visible UI and accessibility copy is localized and audited.
- Terminal chrome is localized; PTY content and terminal environment variables are unchanged.
- Chinese terminology follows the approved glossary and reads as native AI-product copy.
- English remains a complete fallback and existing functionality does not regress.
- Automated tests, type checking, linting, formatting, production build, and required repository checks pass.

