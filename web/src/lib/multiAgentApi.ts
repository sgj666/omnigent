import { authenticatedFetch } from "./identity";

export type AgentBundleValue =
  null | boolean | number | string | AgentBundleValue[] | { [key: string]: AgentBundleValue };

export type BundleValidationStatus = "valid" | "invalid" | "unknown";

export interface MultiAgentSummary {
  id: string;
  name: string;
  description: string | null;
  readonly: boolean;
  harness: string | null;
  worker_count: number;
  skill_count: number;
  mcp_count: number;
  version: number;
  digest: string;
  updated_at: number;
  builtin: boolean;
  editable: boolean;
  validation_status: BundleValidationStatus;
}

export interface StartMultiAgentRunInput {
  agent_id: string;
  workspace_id: string;
  input: string;
  source: "web" | string;
  source_event_id: string;
  host_id?: string;
  execution_mode: "auto" | string;
}

export interface MultiAgentRun {
  id: string;
  status: string;
  agent_id: string;
  workspace_id: string;
  bundle_version?: number | null;
  bundle_digest?: string | null;
}

/** The ledger-backed shape is intentionally open so the inspector can render
 * newer server fields without requiring a Web release first. */
export interface MultiAgentRunRecord {
  id: string;
  status: string;
  workspace_id?: string | null;
  agent_id?: string | null;
  [key: string]: unknown;
}

export interface AgentActivityRun {
  id: string;
  task_id: string;
  task_title: string;
  state: string;
  queued_at: number;
  started_at: number | null;
  finished_at: number | null;
  session_id: string | null;
  runtime_id: string | null;
  workspace: string | null;
  project_id: string | null;
  project_name: string | null;
  waiting_reason: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface AgentActivityProject {
  id: string;
  name: string;
  run_count: number;
}

export interface AgentActivitySkill {
  name: string;
  uses: number;
}

export interface AgentActivity {
  agent_id: string;
  total_runs: number;
  active_runs: number;
  waiting_runs: number;
  failed_runs: number;
  success_rate: number | null;
  recent_runs: AgentActivityRun[];
  projects: AgentActivityProject[];
  skills: AgentActivitySkill[];
  skill_usage_source: "observed_load_skill_calls";
}

export interface AgentBundleFile {
  path: string;
  content: string | null;
  encoding?: "utf-8" | "binary";
  media_type?: string | null;
  size?: number;
  inline?: boolean;
  /** Parsed YAML data, when this file is part of the form-editable AgentSpec. */
  data?: AgentBundleValue;
}

export interface BundleDiagnostic {
  severity: "error" | "warning" | "info";
  code: string;
  file: string | null;
  path: string | null;
  line: number | null;
  column: number | null;
  agent?: string | null;
  worker?: string | null;
  message: string;
  summary_key?: string | null;
}

export interface AgentBundleDraft {
  card: MultiAgentSummary;
  version: number;
  digest: string;
  files: AgentBundleFile[];
  coordinator: AgentBundleFile | null;
  workers: AgentBundleFile[];
  diagnostics: BundleDiagnostic[];
  schema_version: string;
}

export type AgentFormFieldType = "string" | "integer" | "number" | "boolean" | "array" | "object";

export type AgentFormFieldEditor =
  | "text"
  | "textarea"
  | "select"
  | "tri-state"
  | "worker-list"
  | "mcp-list"
  | "policy-map"
  | "sandbox"
  | "terminal-map"
  | "params"
  | "generic-tree";

export interface AgentFormField {
  path: string;
  type: AgentFormFieldType;
  group: string;
  required: boolean;
  default?: AgentBundleValue;
  enum?: AgentBundleValue[];
  secret: boolean;
  translation_key: string;
  help_translation_key?: string | null;
  harnesses?: string[] | null;
  editor?: AgentFormFieldEditor;
}

export interface AgentFormSchema {
  schema_version: string;
  schema?: Record<string, unknown>;
  fields: AgentFormField[];
}

export interface AgentHarnessOption {
  id: string;
  label: string;
  capabilities?: Record<string, unknown>;
  setup_steps?: Record<string, unknown>[];
}

export interface AgentBundleOptions {
  harnesses: AgentHarnessOption[];
  models: Record<string, unknown>[];
  tools: Record<string, unknown>[];
  skills: Record<string, unknown>[];
  mcp: Record<string, unknown>[];
  environment: Record<string, unknown>[];
}

export type AgentBundlePatch =
  | {
      file: string;
      op: "add" | "replace";
      path: string;
      value: AgentBundleValue;
    }
  | {
      file: string;
      op: "remove";
      path: string;
    }
  | {
      file: string;
      op: "replace_file";
      value: string;
    }
  | {
      file: string;
      op: "delete_file";
    };

export type WorkerOperation =
  | { op: "add"; name: string; source: "minimal" | "coordinator" }
  | { op: "copy"; source: string; target: string }
  | { op: "rename"; source: string; target: string }
  | { op: "delete"; name: string; confirmed_references?: string[] };

export interface AgentBundleUpdateRequest {
  expected_version: number;
  patches?: AgentBundlePatch[];
  worker_operations?: WorkerOperation[];
}

export interface CreateAgentBundleInput {
  name: string;
  description?: string;
  config: Record<string, AgentBundleValue>;
}

export interface CloneAgentBundleInput {
  name: string;
  description?: string;
}

export interface AgentBundleValidation {
  valid: boolean;
  diagnostics: BundleDiagnostic[];
  draft?: AgentBundleDraft | null;
}

export class AgentBundleApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly diagnostics: BundleDiagnostic[];

  constructor(
    message: string,
    status: number,
    code: string | null,
    diagnostics: BundleDiagnostic[] = [],
  ) {
    super(message);
    this.name = "AgentBundleApiError";
    this.status = status;
    this.code = code;
    this.diagnostics = diagnostics;
  }
}

export class AgentVersionConflict extends AgentBundleApiError {
  readonly expected_version: number | null;
  readonly server_version: number | null;

  constructor(
    message: string,
    expected_version: number | null,
    server_version: number | null,
    diagnostics: BundleDiagnostic[] = [],
    code: string | null = "conflict",
  ) {
    super(message, 409, code, diagnostics);
    this.name = "AgentVersionConflict";
    this.expected_version = expected_version;
    this.server_version = server_version;
  }
}

interface ListResponse<T> {
  object: "list";
  data: T[];
  has_more?: boolean;
  last_id?: string | null;
}

interface AgentBundleErrorBody {
  error?: { code?: string; message?: string };
  message?: string;
  detail?:
    | string
    | {
        code?: string;
        message?: string;
        expected?: number;
        actual?: number;
        diagnostics?: unknown;
      };
  expected_version?: number;
  server_version?: number;
  actual_version?: number;
  diagnostics?: unknown;
}

function parseBundleDiagnostics(value: unknown): BundleDiagnostic[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is BundleDiagnostic => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
    const diagnostic = item as Record<string, unknown>;
    return (
      (diagnostic.severity === "error" ||
        diagnostic.severity === "warning" ||
        diagnostic.severity === "info") &&
      typeof diagnostic.code === "string" &&
      (typeof diagnostic.file === "string" || diagnostic.file === null) &&
      (typeof diagnostic.path === "string" || diagnostic.path === null) &&
      (typeof diagnostic.line === "number" || diagnostic.line === null) &&
      (typeof diagnostic.column === "number" || diagnostic.column === null) &&
      typeof diagnostic.message === "string"
    );
  });
}

async function errorFromResponse(response: Response): Promise<AgentBundleApiError> {
  const rawBody = (await response.text()).trim();
  let body: AgentBundleErrorBody | null = null;
  try {
    const parsed = JSON.parse(rawBody) as unknown;
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      body = parsed as AgentBundleErrorBody;
    }
  } catch {
    // Plain-text and HTML proxy errors are surfaced verbatim below.
  }
  const detail = typeof body?.detail === "object" ? body.detail : null;
  const structuredMessage =
    body?.error?.message ??
    body?.message ??
    detail?.message ??
    (typeof body?.detail === "string" ? body.detail : undefined);
  const message =
    typeof structuredMessage === "string"
      ? structuredMessage
      : body === null && rawBody
        ? rawBody
        : `${response.status} ${response.statusText}`;
  const code = body?.error?.code ?? detail?.code ?? null;
  const diagnostics = parseBundleDiagnostics(body?.diagnostics ?? detail?.diagnostics);
  if (response.status === 409) {
    return new AgentVersionConflict(
      message,
      body?.expected_version ?? detail?.expected ?? null,
      body?.server_version ?? body?.actual_version ?? detail?.actual ?? null,
      diagnostics,
      code,
    );
  }
  return new AgentBundleApiError(message, response.status, code, diagnostics);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

function archiveForm(bundle: Blob): FormData {
  const body = new FormData();
  body.append("bundle", bundle);
  return body;
}

export async function listMultiAgents(signal?: AbortSignal): Promise<MultiAgentSummary[]> {
  const agents: MultiAgentSummary[] = [];
  const seenAgentIds = new Set<string>();
  const seenCursors = new Set<string>();
  let after: string | null = null;
  /* oxlint-disable no-await-in-loop */
  do {
    signal?.throwIfAborted();
    const url: string =
      after === null ? "/v1/agent-bundles" : `/v1/agent-bundles?after=${encodeURIComponent(after)}`;
    const response: Response = signal
      ? await authenticatedFetch(url, { signal })
      : await authenticatedFetch(url);
    const page: ListResponse<MultiAgentSummary> =
      await readJson<ListResponse<MultiAgentSummary>>(response);
    for (const agent of page.data) {
      if (!seenAgentIds.has(agent.id)) {
        seenAgentIds.add(agent.id);
        agents.push(agent);
      }
    }

    const nextCursor: string | null = page.last_id ?? null;
    if (
      page.has_more !== true ||
      page.data.length === 0 ||
      nextCursor === null ||
      nextCursor === after ||
      seenCursors.has(nextCursor)
    ) {
      after = null;
    } else {
      seenCursors.add(nextCursor);
      after = nextCursor;
    }
  } while (after !== null);
  /* oxlint-enable no-await-in-loop */
  return agents;
}

export async function getAgentBundle(
  agent_id: string,
  signal?: AbortSignal,
): Promise<AgentBundleDraft> {
  const url = `/v1/agent-bundles/${encodeURIComponent(agent_id)}`;
  const response = signal
    ? await authenticatedFetch(url, { signal })
    : await authenticatedFetch(url);
  return readJson<AgentBundleDraft>(response);
}

export async function getAgentActivity(
  agent_id: string,
  signal?: AbortSignal,
): Promise<AgentActivity> {
  const url = `/v1/agent-bundles/${encodeURIComponent(agent_id)}/activity`;
  const response = signal
    ? await authenticatedFetch(url, { signal })
    : await authenticatedFetch(url);
  return readJson<AgentActivity>(response);
}

export async function getAgentFormSchema(signal?: AbortSignal): Promise<AgentFormSchema> {
  const response = signal
    ? await authenticatedFetch("/v1/agent-bundles/schema", { signal })
    : await authenticatedFetch("/v1/agent-bundles/schema");
  return readJson<AgentFormSchema>(response);
}

export async function getAgentBundleOptions(signal?: AbortSignal): Promise<AgentBundleOptions> {
  const response = signal
    ? await authenticatedFetch("/v1/agent-bundles/options", { signal })
    : await authenticatedFetch("/v1/agent-bundles/options");
  return readJson<AgentBundleOptions>(response);
}

export async function validateAgentBundleArchive(bundle: Blob): Promise<AgentBundleValidation> {
  const bytes = new Uint8Array(await bundle.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const response = await authenticatedFetch("/v1/agent-bundles/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bundle_base64: btoa(binary) }),
  });
  return readJson<AgentBundleValidation>(response);
}

export async function createAgentBundle(input: CreateAgentBundleInput): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch("/v1/agent-bundles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function importAgentBundle(bundle: Blob): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch("/v1/agent-bundles/import", {
    method: "POST",
    body: archiveForm(bundle),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function updateAgentBundle(
  agent_id: string,
  request: AgentBundleUpdateRequest,
): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch(`/v1/agent-bundles/${encodeURIComponent(agent_id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function cloneAgentBundle(
  agent_id: string,
  input: CloneAgentBundleInput,
): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch(
    `/v1/agent-bundles/${encodeURIComponent(agent_id)}/clone`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  return readJson<AgentBundleDraft>(response);
}

export async function deleteAgentBundle(agent_id: string): Promise<void> {
  const response = await authenticatedFetch(`/v1/agent-bundles/${encodeURIComponent(agent_id)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw await errorFromResponse(response);
}

export async function exportAgentBundle(agent_id: string): Promise<Blob> {
  const response = await authenticatedFetch(
    `/v1/agent-bundles/${encodeURIComponent(agent_id)}/export`,
  );
  if (!response.ok) throw await errorFromResponse(response);
  return response.blob();
}

export async function startMultiAgentRun(input: StartMultiAgentRunInput): Promise<MultiAgentRun> {
  const response = await authenticatedFetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson<MultiAgentRun>(response);
}

export async function getMultiAgentRun(runId: string): Promise<MultiAgentRunRecord> {
  const response = await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}`);
  return readJson<MultiAgentRunRecord>(response);
}
