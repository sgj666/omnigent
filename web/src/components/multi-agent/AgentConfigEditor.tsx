import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AgentFormSchema, AgentHarnessOption } from "@/lib/multiAgentApi";
import type { AgentConfigDraft } from "@/lib/multiAgentDraft";

const LOCAL_DEFAULT = "__local_default__";
const EMPTY_HARNESSES: AgentHarnessOption[] = [];
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
  schema,
  harnesses = EMPTY_HARNESSES,
}: {
  value: AgentConfigDraft;
  onChange: (value: AgentConfigDraft) => void;
  disabled?: boolean;
  schema?: AgentFormSchema;
  harnesses?: AgentHarnessOption[];
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const set = <K extends keyof AgentConfigDraft>(key: K, next: AgentConfigDraft[K]) =>
    onChange({ ...value, [key]: next });
  const genericFields = (schema?.fields ?? []).filter(
    (field) =>
      field.path !== "/*" &&
      !new Set([
        "/name",
        "/description",
        "/executor",
        "/executor/model",
        "/executor/config/harness",
        "/prompt",
        "/instructions",
        "/tools",
        "/skills",
        "/os_env",
        "/guardrails",
        "/async",
        "/timers",
        "/spawn",
      ]).has(field.path),
  );
  const harnessOptions = value.harness
    ? harnesses.some((option) => option.id === value.harness)
      ? harnesses
      : [{ id: value.harness, label: value.harness }, ...harnesses]
    : harnesses;

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
              {harnessOptions.map((harness) => (
                <SelectItem key={harness.id} value={harness.id}>
                  {harness.label}
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
          <Field key={field} label={t(`fields.${field}`)}>
            <Select
              value={value[field] === undefined ? "default" : value[field] ? "enabled" : "disabled"}
              onValueChange={(next) =>
                set(field, next === "default" ? undefined : next === "enabled")
              }
              disabled={disabled}
            >
              <SelectTrigger aria-label={t(`fields.${field}`)} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">{t("fields.default")}</SelectItem>
                <SelectItem value="enabled">{t("fields.enabled")}</SelectItem>
                <SelectItem value="disabled">{t("fields.disabled")}</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        ))}
      </div>

      {!!genericFields.length && (
        <div className="grid gap-4 lg:grid-cols-2">
          {genericFields.map((field) => (
            <Field
              key={field.path}
              label={t(field.translation_key.replace(/^multiAgent\./, ""), {
                defaultValue: field.path.slice(1),
              })}
              help={
                field.help_translation_key ? t(field.help_translation_key) : t("fields.jsonHelp")
              }
            >
              <Textarea
                aria-label={field.path}
                className="min-h-24 font-mono text-xs"
                value={value.advanced[field.path] ?? ""}
                onChange={(event) =>
                  set("advanced", { ...value.advanced, [field.path]: event.target.value })
                }
                placeholder={
                  field.secret && value.configuredSecrets.includes(field.path)
                    ? t("fields.secretConfigured")
                    : undefined
                }
                disabled={disabled}
              />
            </Field>
          ))}
        </div>
      )}
    </div>
  );
}
