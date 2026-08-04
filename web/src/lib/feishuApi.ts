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
