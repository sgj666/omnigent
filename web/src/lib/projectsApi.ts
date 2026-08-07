// Typed client for the `/v1/projects` first-class projects CRUD
// (`omnigent/server/routes/projects.py`). Projects are owner-private
// containers that group sessions and exist independently of their members —
// so they can be empty, renamed, and deleted without touching sessions.
//
// Session→project membership lives on the session, not here: file/unfile a
// session with `PATCH /v1/sessions/{id}` `{ project_id }` (see sessionsApi).
//
// All requests go through the existing Vite `/v1` proxy. TS surface is
// camelCase-friendly, but the project shape is already flat snake_case-free
// (`id`, `name`), so no boundary conversion is needed.

import { authenticatedFetch } from "./identity";

/**
 * Default session settings a project stores, pre-filled into the new-chat
 * composer. All fields optional — an unset key means "no default for this
 * slot". The vocabulary is client-owned; the server persists the object whole
 * and never acts on it, so adding a key here needs no backend change.
 */
export interface ProjectConfig {
  /** Default host id, or the sandbox sentinel. */
  host_id?: string;
  /** Default working directory / repo path on that host. */
  workspace?: string;
  /** Default agent id for new sessions. */
  agent_id?: string;
  /**
   * Opt-in worktree default: only `true` is meaningful. When `true`, a new
   * session in a git workspace starts in a fresh randomly-named worktree; unset
   * (the only other value the dialog stores) starts directly in the workspace.
   * `false` is never written and is treated the same as unset. The base branch a
   * worktree forks from stays a global preference (Settings › Git), not a
   * project default.
   */
  use_worktree?: boolean;
}

/** A first-class project. Mirrors the `ProjectObject` response shape. */
export interface Project {
  id: string;
  name: string;
  /** Owner user id; `null` in single-user / OSS mode. */
  owner_user_id?: string | null;
  created_at?: number;
  updated_at?: number | null;
  /** Exact count of first-class member sessions returned by collection/detail APIs. */
  session_count?: number;
  /** Artifact summary is present when the server has TaskRun stores wired. */
  artifact_count?: number;
  latest_artifact_name?: string | null;
  latest_artifact_at?: number | null;
  /** Stored default session settings; `{}` when the project has none. */
  config?: ProjectConfig;
}

/** One file output traced back to the TaskRun that created it. */
export interface ProjectArtifact {
  id: string;
  object: "project.artifact";
  project_id: string;
  name: string;
  content_type: string | null;
  bytes: number | null;
  created_at: number | null;
  version: number;
  visibility: "private";
  available: boolean;
  summary: string | null;
  work_item_id: string;
  work_item_title: string;
  work_item_run_id: string;
  session_id: string | null;
  download_url: string | null;
}

interface ProjectListResponse {
  object: "list";
  data: Project[];
}

interface ProjectArtifactListResponse {
  object: "list";
  data: ProjectArtifact[];
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string }; message?: string };
    return body.error?.message ?? body.message ?? `${res.status} ${res.statusText}`;
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/** List the caller's projects (owner-scoped), oldest first. */
export async function listProjects(): Promise<Project[]> {
  const res = await authenticatedFetch("/v1/projects");
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as ProjectListResponse;
  return body.data;
}

/** Fetch a single project (including its `config`) by id. 404s if not owned. */
export async function getProject(id: string): Promise<Project> {
  const res = await authenticatedFetch(`/v1/projects/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Project;
}

/** List real TaskRun file outputs for one owner-private project. */
export async function listProjectArtifacts(id: string): Promise<ProjectArtifact[]> {
  const res = await authenticatedFetch(`/v1/projects/${encodeURIComponent(id)}/artifacts`);
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as ProjectArtifactListResponse;
  return body.data;
}

/**
 * Create a project, optionally with initial `config` defaults. Rejects with the
 * server's message on a duplicate name (409) so callers can surface it inline.
 */
export async function createProject(name: string, config?: ProjectConfig): Promise<Project> {
  const res = await authenticatedFetch("/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config ? { name, config } : { name }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Project;
}

/** Rename a project (O(1) — members reference the id, not the name string). */
export async function renameProject(id: string, name: string): Promise<Project> {
  const res = await authenticatedFetch(`/v1/projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Project;
}

/**
 * Replace a project's stored `config` defaults. Passing `{}` clears them
 * (the server treats `{}` as "clear", distinct from omitting the field, which
 * leaves config unchanged). Only `config` is sent, so the name is untouched.
 */
export async function updateProjectConfig(id: string, config: ProjectConfig): Promise<Project> {
  const res = await authenticatedFetch(`/v1/projects/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as Project;
}

/**
 * Delete a project. Member sessions are kept (never cascade-deleted) and the
 * server clears their first-class `project_id` membership atomically with the
 * container deletion. Returns 404 if not found / not owned.
 */
export async function deleteProject(id: string): Promise<void> {
  const res = await authenticatedFetch(`/v1/projects/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readError(res));
}
