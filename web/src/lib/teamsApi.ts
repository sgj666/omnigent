import { authenticatedFetch } from "./identity";
import { throwApiError } from "./apiError";

export { ApiError, throwApiError } from "./apiError";

export interface TeamMember {
  id?: string;
  name: string;
  role: "coordinator" | "worker";
  harness?: string | null;
  capabilities?: string[];
  concurrency?: number;
  pairing?: Record<string, unknown>;
  surface?: Record<string, unknown>;
}

export interface Team {
  id: string;
  object?: "team";
  name: string;
  status: "active" | "paused" | "archived" | string;
  coordinator: TeamMember;
  workers: TeamMember[];
}

export interface TeamRun {
  id: string;
  object?: "run";
  team_id: string;
  workspace_id: string | null;
  source: string;
  status: string;
  [key: string]: unknown;
}

export interface CreateTeamInput {
  name: string;
  members: TeamMember[];
}

export interface UpdateTeamInput {
  name?: string;
  status?: "active" | "paused" | "archived";
  members?: TeamMember[];
}

interface ListResponse<T> {
  object: "list";
  data: T[];
}

export async function listTeams(): Promise<Team[]> {
  const response = await authenticatedFetch("/v1/teams");
  if (!response.ok) await throwApiError(response);
  return ((await response.json()) as ListResponse<Team>).data;
}

export async function getTeam(teamId: string): Promise<Team> {
  const response = await authenticatedFetch(`/v1/teams/${encodeURIComponent(teamId)}`);
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as Team;
}

export async function createTeam(input: CreateTeamInput): Promise<Team> {
  const response = await authenticatedFetch("/v1/teams", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as Team;
}

export async function updateTeam(teamId: string, input: UpdateTeamInput): Promise<Team> {
  const response = await authenticatedFetch(`/v1/teams/${encodeURIComponent(teamId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as Team;
}

export async function listTeamRuns(teamId: string): Promise<TeamRun[]> {
  const response = await authenticatedFetch(`/v1/teams/${encodeURIComponent(teamId)}/runs`);
  if (!response.ok) await throwApiError(response);
  return ((await response.json()) as ListResponse<TeamRun>).data;
}
