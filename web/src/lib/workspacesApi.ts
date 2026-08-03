import { authenticatedFetch } from "./identity";
import { throwApiError } from "./teamsApi";

export interface WorkspaceRepository {
  name: string;
  path: string;
}

export interface WorkspaceBundle {
  id: string;
  object?: "workspace";
  root_path: string;
  repositories: WorkspaceRepository[];
}

export interface CreateWorkspaceInput {
  root_path: string;
  repositories?: WorkspaceRepository[];
}

export interface SelectWorkspaceInput {
  thread_id: string;
  run_id?: string;
}

export async function listWorkspaces(): Promise<WorkspaceBundle[]> {
  const response = await authenticatedFetch("/v1/workspaces");
  if (!response.ok) await throwApiError(response);
  return ((await response.json()) as { data: WorkspaceBundle[] }).data;
}

export async function createWorkspace(input: CreateWorkspaceInput): Promise<WorkspaceBundle> {
  const response = await authenticatedFetch("/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as WorkspaceBundle;
}

export async function selectWorkspace(
  workspaceId: string,
  input: SelectWorkspaceInput,
): Promise<{ thread_id: string; workspace: WorkspaceBundle }> {
  const response = await authenticatedFetch(`/v1/workspaces/${encodeURIComponent(workspaceId)}/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as { thread_id: string; workspace: WorkspaceBundle };
}

