import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Sentinel Select values for the Model row. Radix requires a non-empty value,
// so the two "no explicit model" choices ride on reserved tokens rather than
// "": DEFAULT = the harness's own configured model (no override), SMART = the
// intelligent router picks per turn.
export const MODEL_SELECT_DEFAULT = "__default__";
export const MODEL_SELECT_SMART = "__smart__";
// Sentinel for the "no explicit effort" (—) choice, same reasoning.
export const EFFORT_SELECT_NONE = "__none__";

// Translate by the persisted option value, not by mutable display copy. This
// keeps configuration controls and summaries in sync while preserving custom
// values (and model ids) that are not part of the built-in glossary.
const OPTION_VALUE_LABEL_KEYS: Record<string, string> = {
  low: "reasoning.low",
  medium: "reasoning.medium",
  high: "reasoning.high",
  xhigh: "reasoning.xhigh",
  max: "reasoning.max",
  default: "reasoning.default",
  none: "reasoning.none",
  auto: "configOptions.labels.auto",
  acceptedits: "configOptions.labels.acceptEdits",
  plan: "configOptions.labels.plan",
  dontask: "configOptions.labels.dontAsk",
  bypasspermissions: "configOptions.labels.bypassPermissions",
  "full-access": "configOptions.labels.fullAccess",
  "read-only": "configOptions.labels.readOnly",
  bypass: "configOptions.labels.bypassApprovalsSandbox",
  "auto-review": "configOptions.labels.autoReview",
  ask: "configOptions.labels.ask",
  yolo: "configOptions.labels.yolo",
};

const OPTION_DESCRIPTION_KEYS: Record<string, string> = {
  "Prompts before edits and commands": "configOptions.descriptions.claudeDefault",
  "Auto-runs; a classifier blocks risky actions": "configOptions.descriptions.claudeAuto",
  "Auto-applies file edits; commands still prompt": "configOptions.descriptions.claudeAcceptEdits",
  "Plans only; makes no edits": "configOptions.descriptions.claudePlan",
  "Auto-denies anything not pre-approved": "configOptions.descriptions.claudeDontAsk",
  "Runs everything; no prompts or safety checks": "configOptions.descriptions.noSafetyChecks",
  "Read/edit/run in workspace; approval for external edits or network":
    "configOptions.descriptions.codexDefault",
  "Edit any file and access the internet without approval":
    "configOptions.descriptions.codexFullAccess",
  "Read files only; approval required for edits, commands, or network":
    "configOptions.descriptions.codexReadOnly",
  "Runs Codex with no approval prompts and no command sandbox":
    "configOptions.descriptions.codexBypass",
  "Normal agent mode; prompts before running commands": "configOptions.descriptions.cursorDefault",
  "Smart Auto: auto-runs safe tool calls and prompts for the rest":
    "configOptions.descriptions.cursorAutoReview",
  "Read-only planning; analyzes and proposes plans, no edits":
    "configOptions.descriptions.cursorPlan",
  "Q&A style; explains and answers questions (read-only)": "configOptions.descriptions.cursorAsk",
  "Runs everything without prompts or safety checks": "configOptions.descriptions.cursorYolo",
};

const OPTION_VALUE_DESCRIPTION_KEYS: Record<string, string> = {
  default: "configOptions.descriptions.claudeDefault",
  auto: "configOptions.descriptions.claudeAuto",
  acceptedits: "configOptions.descriptions.claudeAcceptEdits",
  plan: "configOptions.descriptions.claudePlan",
  dontask: "configOptions.descriptions.claudeDontAsk",
  bypasspermissions: "configOptions.descriptions.noSafetyChecks",
  "full-access": "configOptions.descriptions.codexFullAccess",
  "read-only": "configOptions.descriptions.codexReadOnly",
  bypass: "configOptions.descriptions.codexBypass",
  "auto-review": "configOptions.descriptions.cursorAutoReview",
  ask: "configOptions.descriptions.cursorAsk",
  yolo: "configOptions.descriptions.cursorYolo",
};

export function translateConfigOptionLabel(t: TFunction, value: string, fallback = value): string {
  const key = OPTION_VALUE_LABEL_KEYS[value.trim().toLowerCase()];
  return key ? t(key, { defaultValue: fallback }) : fallback;
}

export function translateConfigOptionDescription(
  t: TFunction,
  value: string,
  fallback: string,
): string {
  const normalized = value.trim().toLowerCase();
  // Descriptions for the shared `default`/`auto`/`plan` values vary by
  // harness, so prefer the canonical description text when present, then
  // fall back to the value map for callers that only provide a value.
  const key = OPTION_DESCRIPTION_KEYS[fallback] ?? OPTION_VALUE_DESCRIPTION_KEYS[normalized];
  return key ? t(key, { defaultValue: fallback }) : fallback;
}

// Claude-native reasoning-effort options for the new-session / scheduled-task
// model+effort pickers. There is deliberately no hardcoded effort default: an
// unselected picker omits `reasoning_effort`, so Claude Code falls back to its
// own configured effort — the same "no override" semantics the in-session
// picker's `null` state uses. Mirrors ANTHROPIC_EFFORTS server-side. Lives here
// (a leaf module, no heavy imports) so both NewChatDialog and the scheduled-task
// dialog can share the single source of truth.
export const CLAUDE_NATIVE_EFFORTS: { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "xHigh" },
  { value: "max", label: "Max" },
];

/**
 * A labeled configuration row: bold label + muted sub-description on the left,
 * the control on the right. Mirrors the "Configure …" modal layout.
 */
export function ConfigRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    // Stacked on mobile (label above a full-width control) so the label never
    // gets squeezed into a narrow column and wraps hard; side-by-side from sm+
    // with the control pinned to a fixed width.
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0 sm:pt-1">
        <div className="text-sm font-medium">{label}</div>
        {description && <div className="text-xs text-muted-foreground">{description}</div>}
      </div>
      <div className="w-full sm:w-52 sm:shrink-0">{children}</div>
    </div>
  );
}

/**
 * A config-modal Select whose options carry descriptions. The description of
 * the hovered / focused option (falling back to the selected one) shows in a
 * footer line pinned at the bottom of the OPEN dropdown. The popup is pinned to
 * the trigger width and the footer wraps, so the dropdown never changes width
 * as you hover across options.
 *
 * @param value Selected option value.
 * @param onValueChange Selection callback.
 * @param options Value/label/description triples.
 * @param testId Trigger test id.
 * @param ariaLabel Accessible name for the trigger (the visible ConfigRow
 *   label is visual-only, so pass it here to name the control for AT).
 */
export function DescribedSelect({
  value,
  onValueChange,
  options,
  testId,
  ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly { value: string; label: string; description: string }[];
  testId: string;
  ariaLabel: string;
}) {
  const { t } = useTranslation("models");
  const translatedLabel = (optionValue: string, label: string) =>
    translateConfigOptionLabel(t, optionValue, label);
  const translatedDescription = (optionValue: string, description: string) =>
    translateConfigOptionDescription(t, optionValue, description);
  const [previewed, setPreviewed] = useState<string | null>(null);
  const detail = options.find((o) => o.value === (previewed ?? value))?.description;
  return (
    <Select
      value={value}
      onValueChange={onValueChange}
      // Reset the preview when the list closes so the next open starts on the
      // selected option's blurb.
      onOpenChange={(next) => {
        if (!next) setPreviewed(null);
      }}
    >
      <SelectTrigger className="w-full" data-testid={testId} aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      {/* Pin the popup to the trigger width so a long blurb wraps in the footer
      instead of widening the list as you hover across options. */}
      <SelectContent
        position="popper"
        align="start"
        className="w-(--radix-select-trigger-width) [&_[data-slot=select-item]]:pl-2.5"
      >
        {options.map((o) => (
          <SelectItem
            key={o.value}
            value={o.value}
            onPointerEnter={() => setPreviewed(o.value)}
            onFocus={() => setPreviewed(o.value)}
          >
            {translatedLabel(o.value, o.label)}
          </SelectItem>
        ))}
        {/* Footer blurb pinned inside the dropdown, tracking the hovered row.
        min-h reserves a line so the popup height doesn't jump as it changes. */}
        <SelectSeparator />
        <p
          data-testid={`${testId}-detail`}
          className="min-h-8 px-2.5 pt-0.5 pb-1 text-xs leading-snug text-muted-foreground"
        >
          {detail ? translatedDescription(previewed ?? value, detail) : detail}
        </p>
      </SelectContent>
    </Select>
  );
}
