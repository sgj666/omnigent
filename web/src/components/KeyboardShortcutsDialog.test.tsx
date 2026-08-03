import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeyboardShortcutsDialog, openKeyboardShortcuts } from "./KeyboardShortcutsDialog";
import { i18n } from "@/i18n";

// The pinned-session row shows in both shells; only its chord differs (Alt in
// the browser). Default the mock to browser (false); flip per-test for native.
const isNativeShell = vi.fn(() => false);
vi.mock("@/lib/nativeBridge", () => ({
  isNativeShell: () => isNativeShell(),
  // DialogContent (rendered here) reads isIOSShell to size modals for the iOS
  // keyboard; this suite exercises the browser path, so it's always false.
  isIOSShell: () => false,
}));

beforeEach(() => {
  isNativeShell.mockReturnValue(false);
});
afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
});

// jsdom's navigator is non-mac, so the modifier glyph renders as "Ctrl".
function toggleViaHotkey() {
  fireEvent.keyDown(window, { key: "/", ctrlKey: true });
}

describe("KeyboardShortcutsDialog", () => {
  it("renders nothing until opened", () => {
    render(<KeyboardShortcutsDialog />);
    expect(screen.queryByText("Send message")).toBeNull();
  });

  it("opens on the modifier+/ hotkey and lists one shortcut from each group", () => {
    render(<KeyboardShortcutsDialog />);
    toggleViaHotkey();

    expect(screen.getByText("Keyboard shortcuts")).toBeTruthy();
    // General / In chats / Navigation / View / Slash commands — one each.
    expect(screen.getByText("Open command palette")).toBeTruthy();
    expect(screen.getByText("Show keyboard shortcuts")).toBeTruthy();
    expect(screen.getByText("Send message")).toBeTruthy();
    expect(screen.getByText("Recall previous prompt")).toBeTruthy();
    expect(screen.getByText("Previous session")).toBeTruthy();
    expect(screen.getByText("Toggle conversations sidebar")).toBeTruthy();
    expect(screen.getByText("Navigate suggestions")).toBeTruthy();
  });

  it("toggles closed on a second hotkey press", async () => {
    render(<KeyboardShortcutsDialog />);
    toggleViaHotkey();
    expect(screen.getByText("Send message")).toBeTruthy();

    toggleViaHotkey();
    await waitFor(() => expect(screen.queryByText("Send message")).toBeNull());
  });

  it("opens when openKeyboardShortcuts() is dispatched (menu entry path)", async () => {
    render(<KeyboardShortcutsDialog />);
    openKeyboardShortcuts();
    // The event dispatch isn't wrapped in act(), so wait for the re-render.
    expect(await screen.findByText("Send message")).toBeTruthy();
  });

  it("shows the pinned-session shortcut with the Alt chord in a plain browser", () => {
    render(<KeyboardShortcutsDialog />);
    toggleViaHotkey();
    const row = screen.getByText("Jump to pinned session (1–10)").closest("li");
    expect(row).toBeTruthy();
    // Browser chord adds Alt (jsdom navigator is non-mac → "Alt") + the 1…0 chip.
    expect(within(row!).getByText("Alt")).toBeTruthy();
    expect(within(row!).getByText("1…0")).toBeTruthy();
  });

  it("shows the pinned-session shortcut without Alt in the Electron shell", () => {
    isNativeShell.mockReturnValue(true);
    render(<KeyboardShortcutsDialog />);
    toggleViaHotkey();
    const row = screen.getByText("Jump to pinned session (1–10)").closest("li");
    expect(row).toBeTruthy();
    expect(within(row!).queryByText("Alt")).toBeNull();
    expect(within(row!).getByText("1…0")).toBeTruthy();
  });

  it("localizes the complete shortcut catalog in Simplified Chinese", async () => {
    await i18n.changeLanguage("zh-CN");
    render(<KeyboardShortcutsDialog />);
    toggleViaHotkey();

    expect(screen.getByText("键盘快捷键")).toBeInTheDocument();
    for (const label of [
      "打开命令面板",
      "发送消息",
      "调出上一条提示词",
      "上一个会话",
      "跳转到已固定会话（1–10）",
      "切换会话侧栏",
      "浏览建议项",
      "应用高亮命令",
      "关闭菜单",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("建议菜单打开时", { exact: false })).toBeInTheDocument();
  });
});
