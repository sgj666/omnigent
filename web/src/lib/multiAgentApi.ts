import { authenticatedFetch } from "./identity";

export type AgentBundleValue =
  null | boolean | number | string | AgentBundleValue[] | { [key: string]: AgentBundleValue };

export type BundleValidationStatus = "valid" | "invalid" | "unknown";
export type BundleFeishuStatus = "connected" | "disconnected" | "pending" | "error";

export interface MultiAgentRecentRun {
  id: string;
  status: string;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface MultiAgentSummary {
  id: string;
  name: string;
  description: string | null;
  harness: string | null;
  model_source: string | null;
  worker_count: number;
  skill_count: number;
  mcp_count: number;
  version: number;
  digest?: string | null;
  updated_at: number | null;
  builtin: boolean;
  editable: boolean;
  validation_status: BundleValidationStatus;
  feishu_status: BundleFeishuStatus;
  recent_run: MultiAgentRecentRun | null;
}

export interface BundleFeishuConnection {
  status: BundleFeishuStatus;
  detail?: string | null;
}

export interface StartMultiAgentRunInput {
  agent_id: string;
  workspace_id: string;
  host_id: string;
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

export interface AgentBundleFile {
  path: string;
  content: string | null;
  encoding?: "utf-8" | "base64";
  media_type?: string | null;
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
  agent: MultiAgentSummary;
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
  fields: AgentFormField[];
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
  shape: "single-agent" | "multi-agent";
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
  ) {
    super(message, 409, "conflict", diagnostics);
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
  detail?: string;
  expected_version?: number;
  server_version?: number;
  actual_version?: number;
  diagnostics?: BundleDiagnostic[];
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
  const structuredMessage = body?.error?.message ?? body?.message ?? body?.detail;
  const message =
    typeof structuredMessage === "string"
      ? structuredMessage
      : body === null && rawBody
        ? rawBody
        : `${response.status} ${response.statusText}`;
  const code = body?.error?.code ?? null;
  const diagnostics = body?.diagnostics ?? [];
  if (response.status === 409) {
    return new AgentVersionConflict(
      message,
      body?.expected_version ?? null,
      body?.server_version ?? body?.actual_version ?? null,
      diagnostics,
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
      after === null ? "/v1/agents" : `/v1/agents?after=${encodeURIComponent(after)}`;
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
  const url = `/v1/agents/${encodeURIComponent(agent_id)}/bundle`;
  const response = signal
    ? await authenticatedFetch(url, { signal })
    : await authenticatedFetch(url);
  return readJson<AgentBundleDraft>(response);
}

export async function getAgentFormSchema(signal?: AbortSignal): Promise<AgentFormSchema> {
  const response = signal
    ? await authenticatedFetch("/v1/agent-spec/schema", { signal })
    : await authenticatedFetch("/v1/agent-spec/schema");
  return readJson<AgentFormSchema>(response);
}

export async function validateAgentBundleArchive(bundle: Blob): Promise<AgentBundleValidation> {
  const response = await authenticatedFetch("/v1/agents/validate", {
    method: "POST",
    body: archiveForm(bundle),
  });
  return readJson<AgentBundleValidation>(response);
}

export async function createAgentBundle(input: CreateAgentBundleInput): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch("/v1/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function importAgentBundle(bundle: Blob): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch("/v1/agents/import", {
    method: "POST",
    body: archiveForm(bundle),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function updateAgentBundle(
  agent_id: string,
  request: AgentBundleUpdateRequest,
): Promise<AgentBundleDraft> {
  const response = await authenticatedFetch(`/v1/agents/${encodeURIComponent(agent_id)}`, {
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
  const response = await authenticatedFetch(`/v1/agents/${encodeURIComponent(agent_id)}/clone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return readJson<AgentBundleDraft>(response);
}

export async function deleteAgentBundle(agent_id: string): Promise<void> {
  const response = await authenticatedFetch(`/v1/agents/${encodeURIComponent(agent_id)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw await errorFromResponse(response);
}

export async function exportAgentBundle(agent_id: string): Promise<Blob> {
  const response = await authenticatedFetch(`/v1/agents/${encodeURIComponent(agent_id)}/export`);
  if (!response.ok) throw await errorFromResponse(response);
  return response.blob();
}

export async function connectAgentBundleFeishu(agent_id: string): Promise<BundleFeishuConnection> {
  const response = await authenticatedFetch(
    `/v1/agents/${encodeURIComponent(agent_id)}/feishu/connect`,
    { method: "POST" },
  );
  return readJson<BundleFeishuConnection>(response);
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
