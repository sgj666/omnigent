import { useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { CheckIcon, ChevronDownIcon, InfoIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type {
  AgentBundleValue,
  AgentFormField,
  AgentFormSchema,
  AgentHarnessOption,
} from "@/lib/multiAgentApi";
import type { AgentConfigDraft } from "@/lib/multiAgentDraft";

const LOCAL_DEFAULT = "__local_default__";
const EMPTY_HARNESSES: AgentHarnessOption[] = [];
const EMPTY_STRINGS: string[] = [];
const STRUCTURED_FIELDS = ["tools", "skills", "mcp", "environment", "guardrails"] as const;
const SYSTEM_PATHS = new Set(["/spec_version", "/executor/type"]);

type JsonObject = Record<string, AgentBundleValue>;

function isObject(value: AgentBundleValue): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isEmpty(value: AgentBundleValue): boolean {
  if (value === null) return true;
  if (Array.isArray(value)) return value.length === 0;
  if (isObject(value)) return Object.keys(value).length === 0;
  return false;
}

function isConfigured(value: string): boolean {
  const source = value.trim();
  return source !== "" && source !== "null" && source !== "{}" && source !== "[]";
}

function parseValue(source: string): AgentBundleValue | undefined {
  if (!source.trim()) return undefined;
  try {
    return JSON.parse(source) as AgentBundleValue;
  } catch {
    return undefined;
  }
}

function writeValue(value: AgentBundleValue | undefined): string {
  return value === undefined ? "" : JSON.stringify(value, null, 2);
}

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
      {help && <p className="text-xs leading-relaxed text-muted-foreground">{help}</p>}
    </div>
  );
}

function keyCopy(t: TFunction, key: string, kind: "label" | "help", path: string[] = []): string {
  const fallback = t(`advancedKeys.${key}.${kind}`, {
    defaultValue: kind === "label" ? key : "",
  });
  return path.length
    ? t(`advancedKeys.${path.join(".")}.${kind}`, { defaultValue: fallback })
    : fallback;
}

function structuredKey(scope: string, path: string[]): string {
  const name = path.at(-1);
  if (name !== "type") return name ?? "value";
  if (scope === "environment" && path.includes("sandbox")) return "sandboxType";
  if (scope === "environment") return "environmentType";
  if (scope === "guardrails" && path.includes("policies")) return "policyType";
  return name;
}

function knownStringOptions(
  t: TFunction,
  scope: string,
  path: string[],
  value: string,
): { value: string; label: string }[] | null {
  let options: { value: string; label: string }[] | null = null;
  const name = path.at(-1);
  if (scope === "environment" && name === "type" && path.includes("sandbox")) {
    options = [
      { value: "none", label: t("fields.noIsolation") },
      { value: "linux_bwrap", label: t("fields.linuxIsolation") },
      { value: "darwin_seatbelt", label: t("fields.macIsolation") },
    ];
  } else if (scope === "environment" && path.length === 1 && name === "type") {
    options = [{ value: "caller_process", label: t("fields.callerProcess") }];
  } else if (scope === "guardrails" && name === "type" && path.includes("policies")) {
    options = [{ value: "function", label: t("fields.functionPolicy") }];
  }
  if (options && !options.some((option) => option.value === value)) {
    options.push({ value, label: value });
  }
  return options;
}

function schemaFieldLabel(t: TFunction, field: AgentFormField): string {
  const knownLabels: Record<string, string> = {
    "/executor/context_window": t("fields.contextWindow"),
    "/executor/auth": t("fields.auth"),
    "/executor/config": t("fields.executorConfig"),
    "/interaction": t("fields.interaction"),
  };
  return (
    knownLabels[field.path] ??
    t(field.translation_key.replace(/^multiAgent\./, ""), {
      defaultValue: field.path.slice(1),
    })
  );
}

function primitiveArrayText(value: AgentBundleValue[]): string {
  return value.map((entry) => String(entry)).join(", ");
}

function parsePrimitiveArray(source: string, original: AgentBundleValue[]): AgentBundleValue[] {
  const entries = source
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  const sample = original.find((entry) => entry !== null);
  if (typeof sample === "number") {
    return entries.map(Number).filter((entry) => Number.isFinite(entry));
  }
  if (typeof sample === "boolean") return entries.map((entry) => entry === "true");
  return entries;
}

function StructuredNode({
  value,
  onChange,
  disabled,
  t,
  scope,
  path = EMPTY_STRINGS,
}: {
  value: AgentBundleValue;
  onChange: (value: AgentBundleValue) => void;
  disabled: boolean;
  t: TFunction;
  scope: string;
  path?: string[];
}) {
  const name = path.at(-1) ?? "value";
  const copyKey = structuredKey(scope, path);
  const copyPath = copyKey === name ? path : EMPTY_STRINGS;
  const label = keyCopy(t, copyKey, "label", copyPath);
  const help = keyCopy(t, copyKey, "help", copyPath);
  const ariaLabel = path.join("/") || label;

  if (typeof value === "boolean") {
    return (
      <Field label={label} help={help}>
        <Select
          value={value ? "true" : "false"}
          onValueChange={(next) => onChange(next === "true")}
          disabled={disabled}
        >
          <SelectTrigger aria-label={ariaLabel} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">{t("fields.enabled")}</SelectItem>
            <SelectItem value="false">{t("fields.disabled")}</SelectItem>
          </SelectContent>
        </Select>
      </Field>
    );
  }

  if (typeof value === "number") {
    return (
      <Field label={label} help={help}>
        <Input
          aria-label={ariaLabel}
          type="number"
          value={String(value)}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isFinite(next)) onChange(next);
          }}
          disabled={disabled}
        />
      </Field>
    );
  }

  if (typeof value === "string") {
    const options = knownStringOptions(t, scope, path, value);
    return (
      <Field label={label} help={help}>
        {options ? (
          <Select value={value} onValueChange={onChange} disabled={disabled}>
            <SelectTrigger aria-label={ariaLabel} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            aria-label={ariaLabel}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            disabled={disabled}
          />
        )}
      </Field>
    );
  }

  if (Array.isArray(value)) {
    const primitive = value.every(
      (entry) => entry === null || ["string", "number", "boolean"].includes(typeof entry),
    );
    if (primitive) {
      return (
        <Field label={label} help={help || t("fields.listHelp")}>
          <Input
            aria-label={ariaLabel}
            value={primitiveArrayText(value)}
            onChange={(event) => onChange(parsePrimitiveArray(event.target.value, value))}
            placeholder={t("fields.listPlaceholder")}
            disabled={disabled}
          />
        </Field>
      );
    }
    return (
      <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">{label}</p>
        <p className="mt-1">{t("fields.complexYamlOnly")}</p>
      </div>
    );
  }

  if (isObject(value)) {
    const entries = Object.entries(value).filter(([, entry]) => entry !== null && !isEmpty(entry));
    const hiddenDefaults = Object.values(value).length - entries.length;
    return (
      <div
        className={path.length ? "space-y-3 rounded-lg border bg-background/50 p-4" : "space-y-3"}
      >
        {path.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-foreground">{label}</p>
            {help && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{help}</p>}
          </div>
        )}
        {entries.map(([key, entry]) => (
          <StructuredNode
            key={key}
            value={entry}
            path={[...path, key]}
            disabled={disabled}
            t={t}
            scope={scope}
            onChange={(next) => onChange({ ...value, [key]: next })}
          />
        ))}
        {entries.length === 0 && (
          <p className="text-xs text-muted-foreground">{t("fields.usesRuntimeDefault")}</p>
        )}
        {hiddenDefaults > 0 && (
          <p className="text-[11px] text-muted-foreground">
            {t("fields.hiddenDefaults", { count: hiddenDefaults })}
          </p>
        )}
      </div>
    );
  }

  return null;
}

function AdvancedSection({
  title,
  help,
  configured,
  children,
}: {
  title: string;
  help: string;
  configured: boolean;
  children: React.ReactNode;
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  return (
    <section className="space-y-4 rounded-xl border bg-muted/10 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">{title}</h4>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{help}</p>
        </div>
        <Badge variant={configured ? "secondary" : "outline"}>
          {configured ? t("fields.configured") : t("fields.usesRuntimeDefault")}
        </Badge>
      </div>
      {children}
    </section>
  );
}

function ToolsEditor({
  source,
  onChange,
  workerNames,
  disabled,
  t,
}: {
  source: string;
  onChange: (source: string) => void;
  workerNames: string[];
  disabled: boolean;
  t: TFunction;
}) {
  const parsed = parseValue(source);
  if (parsed !== undefined && !isObject(parsed)) {
    return <p className="text-xs text-destructive">{t("fields.complexYamlOnly")}</p>;
  }
  const tools = parsed ?? {};
  const selected = Array.isArray(tools.agents)
    ? tools.agents.filter((entry): entry is string => typeof entry === "string")
    : [];
  const choices = Array.from(new Set([...workerNames, ...selected]));
  const extras = Object.fromEntries(
    Object.entries(tools).filter(([key, entry]) => key !== "agents" && entry !== null),
  );

  function toggleAgent(name: string) {
    const agents = selected.includes(name)
      ? selected.filter((entry) => entry !== name)
      : [...selected, name];
    onChange(writeValue({ ...tools, agents }));
  }

  return (
    <div className="space-y-4">
      <Field label={t("fields.collaborators")} help={t("fields.collaboratorsHelp")}>
        {choices.length ? (
          <div className="flex flex-wrap gap-2">
            {choices.map((name) => {
              const active = selected.includes(name);
              return (
                <Button
                  key={name}
                  type="button"
                  variant={active ? "secondary" : "outline"}
                  size="sm"
                  aria-pressed={active}
                  onClick={() => toggleAgent(name)}
                  disabled={disabled}
                >
                  {active && <CheckIcon className="size-3.5" />}
                  {name}
                </Button>
              );
            })}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
            {t("fields.noCollaborators")}
          </p>
        )}
      </Field>
      {Object.keys(extras).length > 0 && (
        <div className="space-y-2 border-t pt-4">
          <p className="text-xs font-medium text-muted-foreground">{t("fields.toolLimits")}</p>
          <StructuredNode
            value={extras}
            onChange={(next) => onChange(writeValue({ ...tools, ...(isObject(next) ? next : {}) }))}
            disabled={disabled}
            t={t}
            scope="tools"
          />
        </div>
      )}
    </div>
  );
}

function SkillsEditor({
  source,
  onChange,
  disabled,
  t,
}: {
  source: string;
  onChange: (source: string) => void;
  disabled: boolean;
  t: TFunction;
}) {
  const parsed = parseValue(source);
  const mode =
    parsed === undefined
      ? "default"
      : parsed === "all"
        ? "all"
        : parsed === "none"
          ? "none"
          : "custom";
  const skills = Array.isArray(parsed)
    ? parsed.filter((entry): entry is string => typeof entry === "string")
    : [];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label={t("fields.skillAccess")} help={t("fields.skillAccessHelp")}>
        <Select
          value={mode}
          onValueChange={(next) => {
            if (next === "default") onChange("");
            else if (next === "all" || next === "none") onChange(JSON.stringify(next));
            else onChange(JSON.stringify(skills));
          }}
          disabled={disabled}
        >
          <SelectTrigger aria-label={t("fields.skillAccess")} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">{t("fields.default")}</SelectItem>
            <SelectItem value="all">{t("fields.allSkills")}</SelectItem>
            <SelectItem value="none">{t("fields.noSkills")}</SelectItem>
            <SelectItem value="custom">{t("fields.selectedSkills")}</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      {mode === "custom" && (
        <Field label={t("fields.skillNames")} help={t("fields.listHelp")}>
          <Input
            aria-label={t("fields.skillNames")}
            value={skills.join(", ")}
            onChange={(event) =>
              onChange(
                JSON.stringify(
                  event.target.value
                    .split(",")
                    .map((entry) => entry.trim())
                    .filter(Boolean),
                ),
              )
            }
            placeholder={t("fields.listPlaceholder")}
            disabled={disabled}
          />
        </Field>
      )}
    </div>
  );
}

function StructuredFieldEditor({
  field,
  source,
  onChange,
  disabled,
  t,
}: {
  field: AgentFormField;
  source: string;
  onChange: (source: string) => void;
  disabled: boolean;
  t: TFunction;
}) {
  const label = schemaFieldLabel(t, field);
  const help = field.help_translation_key
    ? t(field.help_translation_key)
    : t(`advancedPaths.${field.path.slice(1).replaceAll("/", ".")}`, { defaultValue: "" });

  if (field.secret) {
    return (
      <Field label={label} help={help || t("fields.authHelp")}>
        <Input
          type="password"
          aria-label={field.path}
          value={source}
          onChange={(event) => onChange(event.target.value)}
          placeholder={t("fields.secretConfigured")}
          disabled={disabled}
        />
      </Field>
    );
  }

  if (field.type === "boolean") {
    return (
      <Field label={label} help={help}>
        <Select
          value={source || "default"}
          onValueChange={(next) => onChange(next === "default" ? "" : next)}
          disabled={disabled}
        >
          <SelectTrigger aria-label={field.path} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">{t("fields.default")}</SelectItem>
            <SelectItem value="true">{t("fields.enabled")}</SelectItem>
            <SelectItem value="false">{t("fields.disabled")}</SelectItem>
          </SelectContent>
        </Select>
      </Field>
    );
  }

  if (field.type === "integer" || field.type === "number") {
    return (
      <Field label={label} help={help}>
        <Input
          type="number"
          aria-label={field.path}
          value={source}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      </Field>
    );
  }

  if (field.type === "object" || field.type === "array") {
    const parsed = parseValue(source);
    if (parsed === undefined)
      return <p className="text-xs text-muted-foreground">{t("fields.usesRuntimeDefault")}</p>;
    return (
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {help && <p className="text-xs text-muted-foreground">{help}</p>}
        <StructuredNode
          value={parsed}
          onChange={(next) => onChange(writeValue(next))}
          disabled={disabled}
          t={t}
          scope={field.path.slice(1)}
        />
      </div>
    );
  }

  return (
    <Field label={label} help={help}>
      <Input
        aria-label={field.path}
        value={source}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      />
    </Field>
  );
}

export function AgentConfigEditor({
  value,
  onChange,
  disabled = false,
  schema,
  harnesses = EMPTY_HARNESSES,
  workerNames = EMPTY_STRINGS,
}: {
  value: AgentConfigDraft;
  onChange: (value: AgentConfigDraft) => void;
  disabled?: boolean;
  schema?: AgentFormSchema;
  harnesses?: AgentHarnessOption[];
  workerNames?: string[];
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const [showUnusedAdvanced, setShowUnusedAdvanced] = useState(false);
  const set = <K extends keyof AgentConfigDraft>(key: K, next: AgentConfigDraft[K]) =>
    onChange({ ...value, [key]: next });
  const genericFields = (schema?.fields ?? []).filter(
    (field) =>
      field.path !== "/*" &&
      !SYSTEM_PATHS.has(field.path) &&
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
        "/mcp",
        "/mcp_servers",
        "/os_env",
        "/environment",
        "/guardrails",
        "/policies",
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
  const visibleStructuredFields = STRUCTURED_FIELDS.filter(
    (field) => showUnusedAdvanced || isConfigured(value[field]),
  );
  const visibleGenericFields = genericFields.filter(
    (field) =>
      showUnusedAdvanced ||
      isConfigured(value.advanced[field.path] ?? "") ||
      (field.secret && value.configuredSecrets.includes(field.path)),
  );
  const configuredAdvancedCount =
    STRUCTURED_FIELDS.filter((field) => isConfigured(value[field])).length +
    genericFields.filter(
      (field) =>
        isConfigured(value.advanced[field.path] ?? "") ||
        (field.secret && value.configuredSecrets.includes(field.path)),
    ).length;

  return (
    <div className="space-y-5">
      <section className="space-y-5 rounded-xl border bg-muted/15 p-5">
        <div>
          <h3 className="text-sm font-semibold">{t("fields.identity")}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{t("fields.identityHelp")}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("fields.name")}>
            <Input
              aria-label={t("fields.name")}
              value={value.name}
              onChange={(event) => set("name", event.target.value)}
              disabled={disabled}
            />
          </Field>
          <Field label={t("fields.harness")} help={t("fields.harnessHelp")}>
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
          <Field label={t("fields.description")} help={t("fields.descriptionHelp")}>
            <Textarea
              aria-label={t("fields.description")}
              className="min-h-20 resize-y"
              value={value.description}
              onChange={(event) => set("description", event.target.value)}
              disabled={disabled}
            />
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
      </section>

      <section className="space-y-4 rounded-xl border bg-muted/15 p-5">
        <div>
          <h3 className="text-sm font-semibold">{t("fields.instructions")}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{t("fields.instructionsHelp")}</p>
        </div>
        <Textarea
          aria-label={t("fields.prompt")}
          className="min-h-56 font-mono text-xs leading-relaxed"
          value={value.prompt}
          onChange={(event) => set("prompt", event.target.value)}
          disabled={disabled}
        />
      </section>

      <section className="space-y-4 rounded-xl border bg-muted/15 p-5">
        <div>
          <h3 className="text-sm font-semibold">{t("fields.capabilities")}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{t("fields.capabilitiesHelp")}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {(["async", "timers", "spawn"] as const).map((field) => (
            <Field key={field} label={t(`fields.${field}`)} help={t(`fields.${field}Help`)}>
              <Select
                value={
                  value[field] === undefined ? "default" : value[field] ? "enabled" : "disabled"
                }
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
      </section>

      <Collapsible>
        <div className="overflow-hidden rounded-xl border">
          <CollapsibleTrigger className="group flex w-full items-center justify-between gap-4 bg-muted/15 p-5 text-left transition-colors hover:bg-muted/35">
            <div>
              <h3 className="text-sm font-semibold">{t("fields.advancedProperties")}</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("fields.advancedPropertiesHelp")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Badge variant="secondary">
                {t("fields.configuredCount", { count: configuredAdvancedCount })}
              </Badge>
              <ChevronDownIcon className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
            </div>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="space-y-4 border-t p-5">
              <div className="flex gap-2 rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
                <InfoIcon className="mt-0.5 size-4 shrink-0 text-blue-500" />
                <span>{t("fields.advancedVisualHelp")}</span>
              </div>

              {visibleStructuredFields.map((field) => (
                <AdvancedSection
                  key={field}
                  title={t(`fields.${field}`)}
                  help={t(`fields.${field}Help`)}
                  configured={isConfigured(value[field])}
                >
                  {field === "tools" ? (
                    <ToolsEditor
                      source={value.tools}
                      onChange={(next) => set("tools", next)}
                      workerNames={workerNames}
                      disabled={disabled}
                      t={t}
                    />
                  ) : field === "skills" ? (
                    <SkillsEditor
                      source={value.skills}
                      onChange={(next) => set("skills", next)}
                      disabled={disabled}
                      t={t}
                    />
                  ) : parseValue(value[field]) !== undefined ? (
                    <StructuredNode
                      value={parseValue(value[field]) as AgentBundleValue}
                      onChange={(next) => set(field, writeValue(next))}
                      disabled={disabled}
                      t={t}
                      scope={field}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {t("fields.usesRuntimeDefault")}
                    </p>
                  )}
                </AdvancedSection>
              ))}

              {visibleGenericFields.map((field) => (
                <AdvancedSection
                  key={field.path}
                  title={schemaFieldLabel(t, field)}
                  help={t(`advancedPaths.${field.path.slice(1).replaceAll("/", ".")}`, {
                    defaultValue: t("fields.extensionHelp"),
                  })}
                  configured={
                    isConfigured(value.advanced[field.path] ?? "") ||
                    value.configuredSecrets.includes(field.path)
                  }
                >
                  <StructuredFieldEditor
                    field={field}
                    source={value.advanced[field.path] ?? ""}
                    onChange={(next) => set("advanced", { ...value.advanced, [field.path]: next })}
                    disabled={disabled}
                    t={t}
                  />
                </AdvancedSection>
              ))}

              {visibleStructuredFields.length === 0 && visibleGenericFields.length === 0 && (
                <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  {t("fields.noAdvancedConfigured")}
                </p>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowUnusedAdvanced((current) => !current)}
                >
                  {showUnusedAdvanced ? t("fields.hideUnused") : t("fields.showUnused")}
                </Button>
                <p className="text-xs text-muted-foreground">{t("fields.yamlEscapeHatch")}</p>
              </div>
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </div>
  );
}
