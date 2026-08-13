import { authenticatedFetch } from "./identity";

export type SkillValidationStatus = "valid" | "warning" | "error";
export type SkillSyncStatus = "current" | "stale" | "unavailable" | "unconfigured";

export interface SkillRepositorySource {
  remote_url: string;
  ref: string;
  skills_path: string;
  commit_sha: string | null;
  synced_at: number | null;
  sync_status: SkillSyncStatus;
  error: string | null;
  writable: false;
}

export interface SkillSummary {
  id: string;
  object: "skill";
  name: string;
  description: string;
  relative_path: string;
  validation_status: SkillValidationStatus;
  diagnostics: string[];
  file_count: number;
}

export interface SkillFile {
  path: string;
  content: string;
  size: number;
}

export interface SkillDetail extends SkillSummary {
  files: SkillFile[];
  source: SkillRepositorySource;
}

export interface SkillsInventory {
  object: "list";
  data: SkillSummary[];
  source: SkillRepositorySource;
}

export interface SkillsRepositoryConfig {
  object: "skill_repository_config";
  url: string;
  ref: string;
  path: string;
  username: string | null;
  token_configured: boolean;
  editable: boolean;
  source: "database";
}

export interface UpdateSkillsRepositoryConfig {
  url: string;
  ref: string;
  path: string;
  username: string | null;
  token?: string;
}

export interface UpdateSkillsRepositoryConfigResult {
  config: SkillsRepositoryConfig;
  inventory: SkillsInventory;
}

export interface SkillDraftValidation {
  status: SkillValidationStatus;
  diagnostics: string[];
}

export interface SkillDraft {
  skill_id: string;
  baseline_sha: string;
  relative_path: string;
  updated_at: number;
  files: SkillFile[];
  validation: SkillDraftValidation;
}

export interface SkillDraftResponse {
  draft: SkillDraft | null;
  baseline_current: boolean;
  publish_enabled: false;
}

export interface SkillDryRun {
  remote_url: string;
  ref: string;
  baseline_sha: string;
  relative_path: string;
  changed_files: string[];
  diff: string;
  validation: SkillDraftValidation;
  publish_enabled: false;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export async function listSkills(signal?: AbortSignal): Promise<SkillsInventory> {
  const response = await authenticatedFetch("/v1/skills", { signal });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillsInventory;
}

export async function syncSkills(): Promise<SkillsInventory> {
  const response = await authenticatedFetch("/v1/skills/sync", { method: "POST" });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillsInventory;
}

export async function getSkillsRepositoryConfig(
  signal?: AbortSignal,
): Promise<SkillsRepositoryConfig> {
  const response = await authenticatedFetch("/v1/skills/repository-config", { signal });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillsRepositoryConfig;
}

export async function updateSkillsRepositoryConfig(
  config: UpdateSkillsRepositoryConfig,
): Promise<UpdateSkillsRepositoryConfigResult> {
  const response = await authenticatedFetch("/v1/skills/repository-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as UpdateSkillsRepositoryConfigResult;
}

export async function getSkill(id: string, signal?: AbortSignal): Promise<SkillDetail> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}`, { signal });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillDetail;
}

export async function getSkillDraft(id: string, signal?: AbortSignal): Promise<SkillDraftResponse> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}/draft`, {
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillDraftResponse;
}

export async function saveSkillDraft(id: string, files: SkillFile[]): Promise<SkillDraftResponse> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}/draft`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillDraftResponse;
}

export async function validateSkillDraft(
  id: string,
): Promise<{ validation: SkillDraftValidation; baseline_current: boolean }> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}/draft/validate`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as {
    validation: SkillDraftValidation;
    baseline_current: boolean;
  };
}

export async function dryRunSkillDraft(id: string): Promise<SkillDryRun> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}/draft/dry-run`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as SkillDryRun;
}

export async function discardSkillDraft(id: string): Promise<void> {
  const response = await authenticatedFetch(`/v1/skills/${encodeURIComponent(id)}/draft`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await readError(response));
}
