// A read-only "Keyboard shortcuts" overlay listing the shortcuts that already
// exist in the chat surface. It is intentionally a mirror of the live
// behavior — every row here corresponds to a handler that ships today
// (composer `handleKeyDown`, the global session-switch / message-nav hotkeys,
// and the approve hotkey). Nothing here binds new behavior except the dialog's
// own opener (⌘/Ctrl + /), which this component registers.
//
// Self-contained: it owns its open state and listens for its opener directly
// (a window keydown for ⌘/Ctrl+/, plus a custom event so a menu entry can open
// it without prop-drilling). Mount it once near the app shell.

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { isNativeShell } from "@/lib/nativeBridge";

// Custom event the dialog listens for, so non-adjacent surfaces (e.g. the
// account menu) can open it without threading state through the tree.
export const KEYBOARD_SHORTCUTS_EVENT = "omnigent:open-keyboard-shortcuts";

/** Dispatch the open event — used by menu entries that can't reach the state. */
export function openKeyboardShortcuts(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(KEYBOARD_SHORTCUTS_EVENT));
}

// Platform-aware modifier glyphs. macOS shows ⌘/⌥; elsewhere Ctrl/Alt — the
// same split the underlying handlers use (`metaKey || ctrlKey`).
const IS_MAC =
  typeof navigator !== "undefined" &&
  /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "");

/** Modifier label shown in menu hints (⌘ on macOS, Ctrl elsewhere). */
export const MOD_KEY = IS_MAC ? "⌘" : "Ctrl";

// Glyphs match the in-app tooltips (e.g. UserMessageNav's "⌘⌥↑").
const ENTER = "↵";
const SHIFT = "⇧";
const ALT = IS_MAC ? "⌥" : "Alt";
const UP = "↑";
const DOWN = "↓";

interface Shortcut {
  label: string;
  /** Keys rendered left→right as chips. A chord (held together) or, for the
   *  arrow-pairs, the two interchangeable keys for that action. */
  keys: string[];
}

interface ShortcutGroup {
  /** i18n key in the settings namespace. */
  title: string;
  /** Optional qualifier shown next to the group title. */
  note?: string;
  items: Shortcut[];
}

// ONLY shortcuts that exist today (see file header). Keep in sync with the
// composer's `handleKeyDown` and the global hotkey hooks.
const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: "shortcuts.groups.general.title",
    items: [
      { label: "shortcuts.groups.general.openCommandPalette", keys: [MOD_KEY, "K"] },
      { label: "shortcuts.groups.general.showKeyboardShortcuts", keys: [MOD_KEY, "/"] },
    ],
  },
  {
    title: "shortcuts.groups.chat.title",
    items: [
      { label: "shortcuts.groups.chat.sendMessage", keys: [ENTER] },
      { label: "shortcuts.groups.chat.newLine", keys: [SHIFT, ENTER] },
      { label: "shortcuts.groups.chat.recallPreviousPrompt", keys: [UP] },
      { label: "shortcuts.groups.chat.recallNextPrompt", keys: [DOWN] },
      { label: "shortcuts.groups.chat.acceptApprovalPrompt", keys: [MOD_KEY, ENTER] },
      { label: "shortcuts.groups.chat.toggleVoiceDictation", keys: [MOD_KEY, ALT, "V"] },
      { label: "shortcuts.groups.chat.stopResponse", keys: ["Esc"] },
    ],
  },
  {
    title: "shortcuts.groups.navigation.title",
    items: [
      { label: "shortcuts.groups.navigation.previousSession", keys: [MOD_KEY, UP] },
      { label: "shortcuts.groups.navigation.nextSession", keys: [MOD_KEY, DOWN] },
    ],
  },
  {
    title: "shortcuts.groups.view.title",
    items: [
      { label: "shortcuts.groups.view.toggleConversationsSidebar", keys: [MOD_KEY, ALT, "["] },
      { label: "shortcuts.groups.view.toggleWorkspaceSidebar", keys: [MOD_KEY, ALT, "]"] },
    ],
  },
  {
    title: "shortcuts.groups.slash.title",
    note: "shortcuts.groups.slash.suggestionsMenuOpen",
    items: [
      { label: "shortcuts.groups.slash.navigateSuggestions", keys: [UP, DOWN] },
      { label: "shortcuts.groups.slash.applyHighlightedCommand", keys: ["Tab"] },
      { label: "shortcuts.groups.slash.dismissMenu", keys: ["Esc"] },
    ],
  },
];

// Numeric pinned-session jump. The chord is platform-aware (see
// usePinnedSessionHotkeys): plain Cmd/Ctrl+digit in the Electron shell, but
// Cmd/Ctrl+Alt+digit in a browser tab, where plain Cmd+digit is reserved for
// native tab-switching. Shown in both, with the matching glyphs.
function pinnedSessionShortcut(native: boolean): Shortcut {
  return {
    label: "shortcuts.groups.navigation.jumpToPinnedSession",
    keys: native ? [MOD_KEY, "1…0"] : [MOD_KEY, ALT, "1…0"],
  };
}

/** Shortcut groups for the current runtime — the pinned-jump chord differs by shell. */
function shortcutGroupsFor(native: boolean): ShortcutGroup[] {
  return SHORTCUT_GROUPS.map((group) =>
    group.title === "shortcuts.groups.navigation.title"
      ? { ...group, items: [...group.items, pinnedSessionShortcut(native)] }
      : group,
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-6 items-center justify-center rounded-md border border-border bg-muted px-1.5 font-sans text-xs font-medium text-muted-foreground">
      {children}
    </kbd>
  );
}

/**
 * The shortcut reference, grouped, as plain inline content (no dialog
 * chrome). Shared by the {@link KeyboardShortcutsDialog} overlay and the
 * Settings page, which embeds it directly instead of behind a trigger.
 */
export function KeyboardShortcutsList() {
  const { t } = useTranslation("settings");
  // Feature-based, stable per session; computed at render so tests can vary it.
  const groups = shortcutGroupsFor(isNativeShell());
  return (
    <>
      {groups.map((group) => (
        <section key={group.title} className="mb-4 last:mb-0">
          <h3 className="mb-1 text-xs font-medium text-muted-foreground">
            {t(group.title)}
            {group.note ? (
              <span className="ml-1.5 font-normal text-muted-foreground/70">· {t(group.note)}</span>
            ) : null}
          </h3>
          <ul>
            {group.items.map((item) => (
              <li
                key={item.label}
                className="flex items-center justify-between gap-4 border-b border-border/60 py-2.5 last:border-b-0"
              >
                <span className="text-sm text-foreground">{t(item.label)}</span>
                <span className="flex shrink-0 items-center gap-1">
                  {item.keys.map((key) => (
                    <Kbd key={`${item.label}-${key}`}>{key}</Kbd>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

export function KeyboardShortcutsDialog() {
  const { t } = useTranslation("settings");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // ⌘/Ctrl + / toggles the panel. Plain `/` is the composer's slash-menu
      // trigger, so require the modifier and no Shift/Alt to avoid clashing.
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key === "/") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    const onOpenEvent = () => setOpen(true);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener(KEYBOARD_SHORTCUTS_EVENT, onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener(KEYBOARD_SHORTCUTS_EVENT, onOpenEvent);
    };
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("shortcuts.title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("shortcuts.description")}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[70vh] overflow-y-auto pr-1">
          <KeyboardShortcutsList />
        </div>
      </DialogContent>
    </Dialog>
  );
}
