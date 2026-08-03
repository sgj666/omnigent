import { authenticatedFetch } from "./identity";

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

export interface ApiErrorFields {
  status: number;
  failure_code?: string;
  provision_error?: string;
  request_id?: string;
  details?: unknown;
}

/** Error raised by the typed clients while retaining server diagnostics. */
export class ApiError extends Error implements ApiErrorFields {
  readonly status: number;
  readonly failure_code?: string;
  readonly provision_error?: string;
  readonly request_id?: string;
  readonly details?: unknown;

  constructor(message: string, fields: ApiErrorFields) {
    super(message);
    this.name = "ApiError";
    this.status = fields.status;
    this.failure_code = fields.failure_code;
    this.provision_error = fields.provision_error;
    this.request_id = fields.request_id;
    this.details = fields.details;
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; failure_code?: string; provision_error?: string; request_id?: string };
  message?: string;
  detail?: string;
  failure_code?: string;
  provision_error?: string;
  request_id?: string;
  [key: string]: unknown;
}

export async function throwApiError(response: Response): Promise<never> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // Keep the status line when the server did not return JSON.
  }
  const nested = body.error ?? {};
  const requestId = response.headers.get("X-Request-Id") ?? body.request_id ?? nested.request_id;
  const failureCode = body.failure_code ?? nested.failure_code ?? nested.code;
  const provisionError = body.provision_error ?? nested.provision_error;
  const message =
    nested.message ?? body.message ?? body.detail ?? provisionError ?? `${response.status} ${response.statusText}`;
  throw new ApiError(message, {
    status: response.status,
    failure_code: failureCode,
    provision_error: provisionError,
    request_id: requestId ?? undefined,
    details: body,
  });
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

