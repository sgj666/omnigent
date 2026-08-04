import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  cloneAgentBundle,
  createAgentBundle,
  deleteAgentBundle,
  getAgentBundle,
  getAgentFormSchema,
  importAgentBundle,
  listMultiAgents,
  updateAgentBundle,
  validateAgentBundleArchive,
  type AgentBundleUpdateRequest,
  type CloneAgentBundleInput,
  type CreateAgentBundleInput,
} from "@/lib/multiAgentApi";

export const multiAgentsQueryKey = ["multi-agents"] as const;
export const availableAgentsQueryKey = ["available-agents"] as const;
export const agentFormSchemaQueryKey = ["agent-form-schema"] as const;

export function multiAgentQueryKey(agent_id: string) {
  return ["multi-agents", agent_id] as const;
}

function invalidateMultiAgentCaches(queryClient: QueryClient, agent_id?: string) {
  void queryClient.invalidateQueries({ queryKey: multiAgentsQueryKey, exact: true });
  if (agent_id) {
    void queryClient.invalidateQueries({ queryKey: multiAgentQueryKey(agent_id) });
  }
  void queryClient.invalidateQueries({ queryKey: availableAgentsQueryKey });
}

export function useMultiAgents(enabled = true) {
  return useQuery({
    queryKey: multiAgentsQueryKey,
    queryFn: ({ signal }) => listMultiAgents(signal),
    enabled,
  });
}

export function useMultiAgent(agent_id: string | null, enabled = true) {
  return useQuery({
    queryKey: ["multi-agents", agent_id] as const,
    queryFn: ({ signal }) => getAgentBundle(agent_id as string, signal),
    enabled: enabled && agent_id !== null,
  });
}

export function useAgentFormSchema(enabled = true) {
  return useQuery({
    queryKey: agentFormSchemaQueryKey,
    queryFn: ({ signal }) => getAgentFormSchema(signal),
    enabled,
  });
}

export function useValidateAgentBundle() {
  return useMutation({ mutationFn: (bundle: Blob) => validateAgentBundleArchive(bundle) });
}

export function useCreateMultiAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateAgentBundleInput) => createAgentBundle(input),
    onSuccess: (draft) => invalidateMultiAgentCaches(queryClient, draft.agent.id),
  });
}

export function useImportMultiAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (bundle: Blob) => importAgentBundle(bundle),
    onSuccess: (draft) => invalidateMultiAgentCaches(queryClient, draft.agent.id),
  });
}

export function useUpdateMultiAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agent_id, request }: { agent_id: string; request: AgentBundleUpdateRequest }) =>
      updateAgentBundle(agent_id, request),
    onSuccess: (_draft, variables) => invalidateMultiAgentCaches(queryClient, variables.agent_id),
  });
}

export function useCloneMultiAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agent_id, input }: { agent_id: string; input: CloneAgentBundleInput }) =>
      cloneAgentBundle(agent_id, input),
    onSuccess: (draft) => invalidateMultiAgentCaches(queryClient, draft.agent.id),
  });
}

export function useDeleteMultiAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (agent_id: string) => deleteAgentBundle(agent_id),
    onSuccess: (_data, agent_id) => invalidateMultiAgentCaches(queryClient, agent_id),
  });
}
