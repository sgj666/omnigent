import { useQuery } from "@tanstack/react-query";
import { getMultiAgentRun, type MultiAgentRunRecord } from "@/lib/multiAgentApi";

export const runQueryKey = (runId: string) => ["run", runId] as const;

export function useRun(runId: string | null, enabled = true) {
  return useQuery<MultiAgentRunRecord>({
    queryKey: runId === null ? ["run"] : runQueryKey(runId),
    queryFn: () => getMultiAgentRun(runId as string),
    enabled: enabled && runId !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2_000 : false),
  });
}
