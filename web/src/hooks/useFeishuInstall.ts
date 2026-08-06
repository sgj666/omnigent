import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  beginAgentFeishuInstall,
  beginFeishuInstall,
  bindAgentFeishuWorkspace,
  disconnectAgentFeishu,
  getAgentFeishuInstallation,
  getAgentFeishuSurface,
  pollAgentFeishuInstall,
  pollFeishuInstall,
  setAgentFeishuWorkspaceScope,
  reinitializeAgentFeishuSurface,
  getAgentDefaultWorkspaceScope,
  setAgentDefaultWorkspaceScope,
  type AgentFeishuBinding,
  type AgentFeishuInstallation,
  type AgentFeishuSurface,
  type BindAgentFeishuWorkspaceInput,
  type FeishuInstallSession,
  type AgentFeishuWorkspaceScopeInput,
  type AgentDefaultWorkspaceScope,
} from "@/lib/feishuApi";

export const feishuInstallQueryKey = ["feishu-install"] as const;
export const agentFeishuQueryKey = (agentId: string) => ["agent-feishu", agentId] as const;
export const agentFeishuSurfaceQueryKey = (agentId: string) =>
  ["agent-feishu", agentId, "surface"] as const;
export const agentDefaultWorkspaceQueryKey = (agentId: string) =>
  ["agent-default-workspace", agentId] as const;

export function useAgentDefaultWorkspaceScope(agentId: string, enabled = true) {
  return useQuery<AgentDefaultWorkspaceScope | null>({
    queryKey: agentDefaultWorkspaceQueryKey(agentId),
    queryFn: () => getAgentDefaultWorkspaceScope(agentId),
    enabled,
  });
}

export function useSetAgentDefaultWorkspaceScope() {
  const queryClient = useQueryClient();
  return useMutation<
    AgentDefaultWorkspaceScope,
    Error,
    { agentId: string; input: AgentDefaultWorkspaceScope }
  >({
    mutationFn: ({ agentId, input }) => setAgentDefaultWorkspaceScope(agentId, input),
    onSuccess: (scope, { agentId }) =>
      queryClient.setQueryData(agentDefaultWorkspaceQueryKey(agentId), scope),
  });
}

/** Begin a QR/device-flow installation. */
export function useFeishuInstall() {
  const queryClient = useQueryClient();
  return useMutation<FeishuInstallSession, Error, void>({
    mutationKey: feishuInstallQueryKey,
    mutationFn: beginFeishuInstall,
    onSuccess: (session) => {
      queryClient.setQueryData([...feishuInstallQueryKey, session.session], session);
    },
  });
}

/** Poll an installation session. Disabled until a session id is available. */
export function useFeishuInstallStatus(session: FeishuInstallSession | null, enabled = true) {
  const intervalMs = Math.max(session?.interval ?? 5, 1) * 1_000;
  return useQuery({
    queryKey:
      session === null ? feishuInstallQueryKey : [...feishuInstallQueryKey, session.session],
    queryFn: async () => ({
      ...(session as FeishuInstallSession),
      ...(await pollFeishuInstall((session as FeishuInstallSession).session)),
    }),
    enabled: enabled && session !== null,
    initialData: session ?? undefined,
    staleTime: intervalMs,
    refetchInterval: (query) => {
      if (query.state.data?.status !== "pending") return false;
      const interval = query.state.data.interval ?? session?.interval;
      return typeof interval === "number" && interval > 0 ? interval * 1_000 : intervalMs;
    },
  });
}

export function useAgentFeishuConnection(agentId: string, enabled = true) {
  const queryClient = useQueryClient();
  return useQuery<AgentFeishuInstallation | null>({
    queryKey: agentFeishuQueryKey(agentId),
    queryFn: async () => {
      const current = queryClient.getQueryData<AgentFeishuInstallation | null>(
        agentFeishuQueryKey(agentId),
      );
      const session = current?.session ?? current?.device_session;
      if (current?.status === "pending" && session) {
        return { ...current, ...(await pollAgentFeishuInstall(agentId, session)) };
      }
      return getAgentFeishuInstallation(agentId);
    },
    enabled,
    refetchInterval: (query) => {
      if (query.state.data?.status !== "pending") return false;
      return Math.max(query.state.data.interval ?? 5, 1) * 1_000;
    },
  });
}

export function useBeginAgentFeishu() {
  const queryClient = useQueryClient();
  return useMutation<AgentFeishuInstallation, Error, string>({
    mutationFn: beginAgentFeishuInstall,
    onSuccess: (installation, agentId) => {
      queryClient.setQueryData(agentFeishuQueryKey(agentId), installation);
    },
  });
}

export function useDisconnectAgentFeishu() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: disconnectAgentFeishu,
    onSuccess: (_result, agentId) => {
      queryClient.setQueryData(agentFeishuQueryKey(agentId), null);
      queryClient.removeQueries({ queryKey: agentFeishuSurfaceQueryKey(agentId) });
    },
  });
}

export function useBindAgentFeishuWorkspace() {
  const queryClient = useQueryClient();
  return useMutation<
    AgentFeishuBinding,
    Error,
    { agentId: string; input: BindAgentFeishuWorkspaceInput }
  >({
    mutationFn: ({ agentId, input }) => bindAgentFeishuWorkspace(agentId, input),
    onSuccess: (binding, { agentId }) => {
      queryClient.setQueryData<AgentFeishuInstallation | null>(
        agentFeishuQueryKey(agentId),
        (current) => (current ? { ...current, binding } : current),
      );
    },
  });
}

export function useSetAgentFeishuWorkspaceScope() {
  const queryClient = useQueryClient();
  return useMutation<
    AgentFeishuInstallation,
    Error,
    { agentId: string; input: AgentFeishuWorkspaceScopeInput }
  >({
    mutationFn: ({ agentId, input }) => setAgentFeishuWorkspaceScope(agentId, input),
    onSuccess: (installation, { agentId }) => {
      queryClient.setQueryData(agentFeishuQueryKey(agentId), installation);
    },
  });
}

export function useAgentFeishuSurface(agentId: string, enabled = true) {
  return useQuery<AgentFeishuSurface>({
    queryKey: agentFeishuSurfaceQueryKey(agentId),
    queryFn: () => getAgentFeishuSurface(agentId),
    enabled,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 2_000 : false),
  });
}

export function useReinitializeAgentFeishuSurface() {
  const queryClient = useQueryClient();
  return useMutation<AgentFeishuSurface, Error, string>({
    mutationFn: reinitializeAgentFeishuSurface,
    onSuccess: (surface, agentId) => {
      queryClient.setQueryData(agentFeishuSurfaceQueryKey(agentId), surface);
    },
  });
}
