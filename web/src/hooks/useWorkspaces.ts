import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createWorkspace,
  listWorkspaces,
  selectWorkspace,
  type CreateWorkspaceInput,
  type SelectWorkspaceInput,
  type WorkspaceBundle,
} from "@/lib/workspacesApi";

export const workspacesQueryKey = ["workspaces"] as const;

export function useWorkspaces(enabled = true) {
  return useQuery({ queryKey: workspacesQueryKey, queryFn: listWorkspaces, enabled });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation<WorkspaceBundle, Error, CreateWorkspaceInput>({
    mutationFn: createWorkspace,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
    },
  });
}

export interface SelectWorkspaceVariables extends SelectWorkspaceInput {
  workspaceId: string;
}

export function useSelectWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ workspaceId, ...input }: SelectWorkspaceVariables) =>
      selectWorkspace(workspaceId, input),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
      if (result.thread_id) {
        void queryClient.invalidateQueries({ queryKey: ["team-runs"] });
      }
    },
  });
}
