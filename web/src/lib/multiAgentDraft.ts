import { isMap, LineCounter, parseDocument, YAMLError } from "yaml";
import type {
  AgentBundleFile,
  AgentBundlePatch,
  AgentBundleValue,
  AgentFormSchema,
} from "./multiAgentApi";

interface JsonObject {
  [key: string]: AgentBundleValue;
}

export interface AgentConfigDraft {
  name: string;
  description: string;
  harness: string;
  model: string;
  prompt: string;
  tools: string;
  skills: string;
  mcp: string;
  environment: string;
  guardrails: string;
  policies: string;
  async: boolean | undefined;
  timers: boolean | undefined;
  spawn: boolean | undefined;
  advanced: Record<string, string>;
  configuredSecrets: string[];
}

export class DraftJsonError extends Error {
  readonly field: keyof AgentConfigDraft;

  constructor(field: keyof AgentConfigDraft) {
    super(`Invalid JSON in ${field}`);
    this.name = "DraftJsonError";
    this.field = field;
  }
}

function object(value: AgentBundleValue | undefined): JsonObject | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : undefined;
}

function at(root: AgentBundleValue, path: readonly string[]): AgentBundleValue | undefined {
  let value: AgentBundleValue | undefined = root;
  for (const part of path) {
    value = object(value)?.[part];
    if (value === undefined) return undefined;
  }
  return value;
}

function text(value: AgentBundleValue | undefined): string {
  return typeof value === "string" ? value : "";
}

function json(value: AgentBundleValue | undefined): string {
  return value === undefined ? "" : JSON.stringify(value, null, 2);
}

function pointerParts(pointer: string): string[] {
  return pointer
    .slice(1)
    .split("/")
    .filter(Boolean)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
}

const OWNED_SCHEMA_PATHS = new Set([
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
]);

export function readAgentConfig(
  value: AgentBundleValue,
  referencedPrompt?: string,
  schema?: AgentFormSchema,
): AgentConfigDraft {
  const harness = at(value, ["executor", "config", "harness"]);
  const model = at(value, ["executor", "model"]) ?? at(value, ["executor", "config", "model"]);
  const advanced: Record<string, string> = {};
  const knownRoots = new Set([
    "name",
    "description",
    "executor",
    "prompt",
    "instructions",
    "tools",
    "skills",
    "os_env",
    "guardrails",
    "async",
    "timers",
    "spawn",
  ]);
  const root = object(value);
  for (const [key, entry] of Object.entries(root ?? {})) {
    if (!knownRoots.has(key)) advanced[`/${key}`] = typeof entry === "string" ? entry : json(entry);
  }
  const configuredSecrets: string[] = [];
  for (const field of schema?.fields ?? []) {
    if (field.path === "/*" || OWNED_SCHEMA_PATHS.has(field.path)) continue;
    const current = at(value, pointerParts(field.path));
    if (field.secret) {
      if (current !== undefined) configuredSecrets.push(field.path);
      continue;
    }
    if (current === undefined) continue;
    if (field.path === "/executor/config") {
      const config = object(current);
      const extension = Object.fromEntries(
        Object.entries(config ?? {}).filter(([key]) => key !== "harness" && key !== "model"),
      ) as JsonObject;
      advanced[field.path] = json(extension);
    } else {
      advanced[field.path] = typeof current === "string" ? current : json(current);
    }
  }
  return {
    name: text(at(value, ["name"])),
    description: text(at(value, ["description"])),
    harness: text(harness),
    model: text(model),
    prompt: referencedPrompt ?? text(at(value, ["prompt"]) ?? at(value, ["instructions"])),
    tools: json(at(value, ["tools"])),
    skills: json(at(value, ["skills"])),
    mcp: json(at(value, ["tools", "mcp"])),
    environment: json(at(value, ["os_env"])),
    guardrails: json(at(value, ["guardrails"])),
    policies: json(at(value, ["policies"])),
    async:
      typeof at(value, ["async"]) === "boolean" ? (at(value, ["async"]) as boolean) : undefined,
    timers:
      typeof at(value, ["timers"]) === "boolean" ? (at(value, ["timers"]) as boolean) : undefined,
    spawn:
      typeof at(value, ["spawn"]) === "boolean" ? (at(value, ["spawn"]) as boolean) : undefined,
    advanced,
    configuredSecrets,
  };
}

function parseJsonField(
  draft: AgentConfigDraft,
  field: "tools" | "skills" | "mcp" | "environment" | "guardrails" | "policies",
): AgentBundleValue | undefined {
  const source = draft[field].trim();
  if (!source) return undefined;
  try {
    return JSON.parse(source) as AgentBundleValue;
  } catch {
    throw new DraftJsonError(field);
  }
}

function has(root: AgentBundleValue, path: readonly string[]): boolean {
  return at(root, path) !== undefined;
}

function equal(left: AgentBundleValue | undefined, right: AgentBundleValue | undefined): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function patch(
  file: string,
  original: AgentBundleValue,
  path: readonly string[],
  desired: AgentBundleValue | undefined,
): AgentBundlePatch | null {
  const current = at(original, path);
  if (equal(current, desired)) return null;
  const pointer = `/${path.map((part) => part.replace(/~/g, "~0").replace(/\//g, "~1")).join("/")}`;
  if (desired === undefined) {
    return has(original, path) ? { file, op: "remove", path: pointer } : null;
  }
  return {
    file,
    op: has(original, path) ? "replace" : "add",
    path: pointer,
    value: desired,
  };
}

export interface PromptReference {
  path: string;
  content: string;
}

export function buildConfigPatches(
  file: string,
  original: AgentBundleValue,
  draft: AgentConfigDraft,
  options: { reference?: PromptReference | null } = {},
): AgentBundlePatch[] {
  const modelPath = has(original, ["executor", "config", "model"])
    ? ["executor", "config", "model"]
    : ["executor", "model"];
  const candidates: (AgentBundlePatch | null)[] = [
    patch(file, original, ["name"], draft.name.trim() || undefined),
    patch(file, original, ["description"], draft.description.trim() || undefined),
    patch(file, original, ["executor", "config", "harness"], draft.harness.trim() || undefined),
    patch(file, original, modelPath, draft.model.trim() || undefined),
    options.reference
      ? draft.prompt === options.reference.content
        ? null
        : { file: options.reference.path, op: "replace_file" as const, value: draft.prompt }
      : patch(file, original, ["prompt"], draft.prompt || undefined),
    patch(file, original, ["tools"], parseJsonField(draft, "tools")),
    patch(file, original, ["skills"], parseJsonField(draft, "skills")),
    patch(file, original, ["tools", "mcp"], parseJsonField(draft, "mcp")),
    patch(file, original, ["os_env"], parseJsonField(draft, "environment")),
    patch(file, original, ["guardrails"], parseJsonField(draft, "guardrails")),
    patch(file, original, ["policies"], parseJsonField(draft, "policies")),
    patch(file, original, ["async"], draft.async),
    patch(file, original, ["timers"], draft.timers),
    patch(file, original, ["spawn"], draft.spawn),
  ];
  for (const [pointer, source] of Object.entries(draft.advanced)) {
    if (draft.configuredSecrets.includes(pointer) && !source.trim()) continue;
    const path = pointerParts(pointer);
    const current = at(original, path);
    let desired: AgentBundleValue | undefined;
    if (!source.trim()) desired = undefined;
    else if (typeof current === "string" || current === undefined) {
      try {
        desired = JSON.parse(source) as AgentBundleValue;
      } catch {
        desired = source;
      }
    } else {
      try {
        desired = JSON.parse(source) as AgentBundleValue;
      } catch {
        throw new DraftJsonError("advanced");
      }
    }
    if (pointer === "/executor/config") {
      if (desired === undefined) desired = {};
      const extension = object(desired);
      if (extension === undefined) throw new DraftJsonError("advanced");
      const originalConfig = object(current) ?? {};
      const keys = new Set([
        ...Object.keys(originalConfig).filter((key) => key !== "harness" && key !== "model"),
        ...Object.keys(extension),
      ]);
      for (const key of keys) {
        candidates.push(patch(file, original, ["executor", "config", key], extension[key]));
      }
    } else {
      candidates.push(patch(file, original, path, desired));
    }
  }
  return candidates.filter((value): value is AgentBundlePatch => value !== null);
}

export function resolvePromptFile(
  configPath: string,
  data: AgentBundleValue,
  files: Pick<AgentBundleFile, "path" | "content">[],
): PromptReference | null {
  const reference = at(data, ["instructions"]);
  if (
    typeof reference !== "string" ||
    !reference ||
    reference.includes("\\") ||
    reference.startsWith("/") ||
    /^[A-Za-z][A-Za-z0-9+.-]*:/.test(reference)
  ) {
    return null;
  }
  const parts = reference.split("/");
  if (parts.some((part) => part === ".." || part === "")) return null;
  const base = configPath.split("/").slice(0, -1);
  const path = [...base, ...parts.filter((part) => part !== ".")].join("/");
  const file = files.find((candidate) => candidate.path === path && candidate.content !== null);
  return file?.content == null ? null : { path, content: file.content };
}

export interface YamlDiagnostic {
  line: number;
  column: number;
  message: string;
}

export type ParsedAgentYaml =
  { data: AgentBundleValue; diagnostic: null } | { data: null; diagnostic: YamlDiagnostic };

function diagnosticFromYamlError(error: YAMLError, lineCounter: LineCounter): YamlDiagnostic {
  const position = error.linePos?.[0] ?? lineCounter.linePos(error.pos[0]);
  return { line: position.line, column: position.col, message: error.message };
}

function rootDiagnostic(source: string, lineCounter: LineCounter): YamlDiagnostic {
  const firstContent = source.search(/\S/);
  const position = lineCounter.linePos(firstContent === -1 ? 0 : firstContent);
  return { line: position.line, column: position.col, message: "Expected a YAML mapping" };
}

export function parseAgentYaml(source: string): ParsedAgentYaml {
  const lineCounter = new LineCounter();
  const document = parseDocument(source, {
    lineCounter,
    merge: true,
    prettyErrors: false,
    schema: "core",
    stringKeys: true,
    uniqueKeys: true,
  });
  const parseError = document.errors[0];
  if (parseError) {
    return { data: null, diagnostic: diagnosticFromYamlError(parseError, lineCounter) };
  }
  if (document.contents === null) return { data: {}, diagnostic: null };
  if (!isMap(document.contents)) {
    return { data: null, diagnostic: rootDiagnostic(source, lineCounter) };
  }
  try {
    return { data: document.toJS({ maxAliasCount: 100 }) as AgentBundleValue, diagnostic: null };
  } catch (error) {
    if (error instanceof YAMLError) {
      return { data: null, diagnostic: diagnosticFromYamlError(error, lineCounter) };
    }
    return {
      data: null,
      diagnostic: {
        line: 1,
        column: 1,
        message: error instanceof Error ? error.message : "Invalid YAML",
      },
    };
  }
}
export function workerName(path: string, data: AgentBundleValue | undefined): string {
  const configured = data === undefined ? undefined : at(data, ["name"]);
  if (typeof configured === "string" && configured) return configured;
  const parts = path.split("/");
  return parts.length > 2 ? parts[parts.length - 2] : path;
}
