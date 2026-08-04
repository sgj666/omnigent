import { authenticatedFetch } from "./identity";
import { throwApiError } from "./apiError";

export interface FeishuInstallSession {
  object?: "feishu.installation_session";
  session: string;
  verification_uri_complete?: string;
  interval?: number;
  expires_in?: number;
  status: "pending" | "active" | "expired" | string;
  [key: string]: unknown;
}

export type AgentFeishuStatus = "pending" | "connected" | "expired" | "error" | string;

export interface AgentFeishuBinding {
  id?: string;
  installation_id: string;
  chat_id: string;
  thread_id?: string | null;
  workspace_id?: string | null;
  host_id?: string | null;
  execution_mode?: string;
}

export interface AgentFeishuInstallation {
  id: string;
  agent_id: string;
  status: AgentFeishuStatus;
  session?: string | null;
  device_session?: string | null;
  verification_uri?: string | null;
  verification_uri_complete?: string | null;
  user_code?: string | null;
  interval?: number | null;
  expires_in?: number | null;
  app_id?: string | null;
  tenant_name?: string | null;
  tenant_key?: string | null;
  installer_open_id?: string | null;
  bot_open_id?: string | null;
  bot_name?: string | null;
  error?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
  binding?: AgentFeishuBinding | null;
  surface?: AgentFeishuSurface | null;
  [key: string]: unknown;
}

export interface AgentFeishuSurface {
  installation_id?: string;
  surface_profile_id?: string;
  surface_version?: number;
  status: "pending" | "ready" | "partial" | "failed" | string;
  surface_type?: "menu" | "persistent_card" | "none" | string;
  error?: string | null;
  last_provisioned_at?: number | null;
  provider_resource_id?: string | null;
  [key: string]: unknown;
}

export interface BindAgentFeishuWorkspaceInput {
  installation_id: string;
  chat_id: string;
  thread_id?: string | null;
  workspace_id?: string | null;
  host_id?: string | null;
  execution_mode?: string;
  allowed_members?: string[];
}

function agentFeishuPath(agentId: string, suffix = ""): string {
  return `/v1/agents/${encodeURIComponent(agentId)}/feishu${suffix}`;
}

async function readAgentJson<T>(response: Response): Promise<T> {
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as T;
}

export async function beginAgentFeishuInstall(agentId: string): Promise<AgentFeishuInstallation> {
  return readAgentJson<AgentFeishuInstallation>(
    await authenticatedFetch(agentFeishuPath(agentId, "/installations"), { method: "POST" }),
  );
}

export async function pollAgentFeishuInstall(
  agentId: string,
  session: string,
): Promise<AgentFeishuInstallation> {
  return readAgentJson<AgentFeishuInstallation>(
    await authenticatedFetch(
      agentFeishuPath(agentId, `/installations/${encodeURIComponent(session)}`),
    ),
  );
}

export async function getAgentFeishuInstallation(
  agentId: string,
): Promise<AgentFeishuInstallation | null> {
  const response = await authenticatedFetch(agentFeishuPath(agentId));
  if (response.status === 404) return null;
  return readAgentJson<AgentFeishuInstallation>(response);
}

export async function disconnectAgentFeishu(agentId: string): Promise<void> {
  const response = await authenticatedFetch(agentFeishuPath(agentId), { method: "DELETE" });
  if (!response.ok) await throwApiError(response);
}

export async function bindAgentFeishuWorkspace(
  agentId: string,
  input: BindAgentFeishuWorkspaceInput,
): Promise<AgentFeishuBinding> {
  return readAgentJson<AgentFeishuBinding>(
    await authenticatedFetch(agentFeishuPath(agentId, "/binding"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  );
}

export async function getAgentFeishuSurface(agentId: string): Promise<AgentFeishuSurface> {
  return readAgentJson<AgentFeishuSurface>(
    await authenticatedFetch(agentFeishuPath(agentId, "/surface/status")),
  );
}

export async function reinitializeAgentFeishuSurface(agentId: string): Promise<AgentFeishuSurface> {
  return readAgentJson<AgentFeishuSurface>(
    await authenticatedFetch(agentFeishuPath(agentId, "/surface/reinitialize"), {
      method: "POST",
    }),
  );
}

export async function beginFeishuInstall(): Promise<FeishuInstallSession> {
  const response = await authenticatedFetch("/v1/feishu/installations", { method: "POST" });
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as FeishuInstallSession;
}

export async function pollFeishuInstall(session: string): Promise<FeishuInstallSession> {
  const response = await authenticatedFetch(
    `/v1/feishu/installations/${encodeURIComponent(session)}`,
  );
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as FeishuInstallSession;
}

// Short aliases keep the API surface pleasant for callers that already have
// an installation context.
export const beginInstallation = beginFeishuInstall;
export const pollInstallation = pollFeishuInstall;
