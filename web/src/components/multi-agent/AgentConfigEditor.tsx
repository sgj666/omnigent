import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { AgentConfigDraft } from "@/lib/multiAgentDraft";

const LOCAL_DEFAULT = "__local_default__";
const HARNESS_OPTIONS = [
  "claude-sdk",
  "codex-native",
  "claude-native",
  "opencode-native",
  "cursor-native",
  "hermes-native",
  "antigravity-native",
  "pi",
];

function Field({
  label,
  children,
  help,
}: {
  label: string;
  children: React.ReactNode;
  help?: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {children}
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}

export function AgentConfigEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: AgentConfigDraft;
  onChange: (value: AgentConfigDraft) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const set = <K extends keyof AgentConfigDraft>(key: K, next: AgentConfigDraft[K]) =>
    onChange({ ...value, [key]: next });

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("fields.name")}>
          <Input
            aria-label={t("fields.name")}
            value={value.name}
            onChange={(event) => set("name", event.target.value)}
            disabled={disabled}
          />
        </Field>
        <Field label={t("fields.description")}>
          <Input
            aria-label={t("fields.description")}
            value={value.description}
            onChange={(event) => set("description", event.target.value)}
            disabled={disabled}
          />
        </Field>
        <Field label={t("fields.harness")}>
          <Select
            value={value.harness || LOCAL_DEFAULT}
            onValueChange={(next) => set("harness", next === LOCAL_DEFAULT ? "" : next)}
            disabled={disabled}
          >
            <SelectTrigger aria-label={t("fields.harness")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={LOCAL_DEFAULT}>{t("fields.localDefault")}</SelectItem>
              {HARNESS_OPTIONS.map((harness) => (
                <SelectItem key={harness} value={harness}>
                  {harness}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label={t("fields.model")} help={t("fields.localDefaultHelp")}>
          <Input
            aria-label={t("fields.model")}
            value={value.model}
            onChange={(event) => set("model", event.target.value)}
            placeholder={t("fields.localDefault")}
            disabled={disabled}
          />
          {!value.model && (
            <p className="text-xs font-medium text-primary">{t("fields.localDefault")}</p>
          )}
        </Field>
      </div>

      <Field label={t("fields.prompt")}>
        <Textarea
          aria-label={t("fields.prompt")}
          className="min-h-40 font-mono text-xs"
          value={value.prompt}
          onChange={(event) => set("prompt", event.target.value)}
          disabled={disabled}
        />
      </Field>

      <div className="grid gap-4 lg:grid-cols-2">
        {(["tools", "skills", "mcp", "environment", "guardrails", "policies"] as const).map(
          (field) => (
            <Field key={field} label={t(`fields.${field}`)} help={t("fields.jsonHelp")}>
              <Textarea
                aria-label={t(`fields.${field}`)}
                className="min-h-32 font-mono text-xs"
                value={value[field]}
                onChange={(event) => set(field, event.target.value)}
                placeholder="{}"
                disabled={disabled}
              />
            </Field>
          ),
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {(["async", "timers", "spawn"] as const).map((field) => (
          <label
            key={field}
            className="flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5 text-sm"
          >
            <span>{t(`fields.${field}`)}</span>
            <Switch
              checked={value[field]}
              onCheckedChange={(checked) => set(field, checked)}
              disabled={disabled}
            />
          </label>
        ))}
      </div>
    </div>
  );
}
