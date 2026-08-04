import type { AgentBundlePatch, AgentBundleValue } from "./multiAgentApi";

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
  async: boolean;
  timers: boolean;
  spawn: boolean;
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

export function readAgentConfig(value: AgentBundleValue): AgentConfigDraft {
  const harness = at(value, ["executor", "config", "harness"]);
  const model = at(value, ["executor", "model"]) ?? at(value, ["executor", "config", "model"]);
  return {
    name: text(at(value, ["name"])),
    description: text(at(value, ["description"])),
    harness: text(harness),
    model: text(model),
    prompt: text(at(value, ["prompt"]) ?? at(value, ["instructions"])),
    tools: json(at(value, ["tools"])),
    skills: json(at(value, ["skills"])),
    mcp: json(at(value, ["tools", "mcp"])),
    environment: json(at(value, ["os_env"])),
    guardrails: json(at(value, ["guardrails"])),
    policies: json(at(value, ["guardrails", "policies"])),
    async: at(value, ["async"]) !== false,
    timers: at(value, ["timers"]) === true,
    spawn: at(value, ["spawn"]) === true,
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
  const pointer = `/${path.join("/")}`;
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

function defaultedBooleanPatch(
  file: string,
  original: AgentBundleValue,
  path: readonly string[],
  desired: boolean,
  defaultValue: boolean,
): AgentBundlePatch | null {
  const current = at(original, path);
  if ((typeof current === "boolean" ? current : defaultValue) === desired) return null;
  return patch(file, original, path, desired);
}

export function buildConfigPatches(
  file: string,
  original: AgentBundleValue,
  draft: AgentConfigDraft,
): AgentBundlePatch[] {
  const modelPath = has(original, ["executor", "config", "model"])
    ? ["executor", "config", "model"]
    : ["executor", "model"];
  const candidates: (AgentBundlePatch | null)[] = [
    patch(file, original, ["name"], draft.name.trim() || undefined),
    patch(file, original, ["description"], draft.description.trim() || undefined),
    patch(file, original, ["executor", "config", "harness"], draft.harness.trim() || undefined),
    patch(file, original, modelPath, draft.model.trim() || undefined),
    patch(file, original, ["prompt"], draft.prompt || undefined),
    patch(file, original, ["tools"], parseJsonField(draft, "tools")),
    patch(file, original, ["skills"], parseJsonField(draft, "skills")),
    patch(file, original, ["tools", "mcp"], parseJsonField(draft, "mcp")),
    patch(file, original, ["os_env"], parseJsonField(draft, "environment")),
    patch(file, original, ["guardrails"], parseJsonField(draft, "guardrails")),
    patch(file, original, ["guardrails", "policies"], parseJsonField(draft, "policies")),
    defaultedBooleanPatch(file, original, ["async"], draft.async, true),
    defaultedBooleanPatch(file, original, ["timers"], draft.timers, false),
    defaultedBooleanPatch(file, original, ["spawn"], draft.spawn, false),
  ];
  return candidates.filter((value): value is AgentBundlePatch => value !== null);
}

export function workerName(path: string, data: AgentBundleValue | undefined): string {
  const configured = data === undefined ? undefined : at(data, ["name"]);
  if (typeof configured === "string" && configured) return configured;
  const parts = path.split("/");
  return parts.length > 2 ? parts[parts.length - 2] : path;
}
