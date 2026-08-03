import { useQuery } from "@tanstack/react-query";
import { authenticatedFetch } from "@/lib/identity";
import { listTeamRuns, throwApiError, type TeamRun } from "@/lib/teamsApi";

/** The ledger-backed shape is intentionally open: newer server fields are
 * rendered by the inspector without requiring a web release first. */
export type TeamRunRecord = TeamRun & Record<string, unknown>;

export const teamRunsQueryKey = (teamId: string) => ["team-runs", teamId] as const;
export const teamRunQueryKey = (runId: string) => ["team-run", runId] as const;

export function useTeamRuns(teamId: string | null, enabled = true) {
  return useQuery<TeamRun[]>({
    queryKey: teamId === null ? ["team-runs"] : teamRunsQueryKey(teamId),
    queryFn: () => listTeamRuns(teamId as string),
    enabled: enabled && teamId !== null,
  });
}

/** Fetch one complete run trace from the Durable Ledger. */
export async function getTeamRun(runId: string): Promise<TeamRunRecord> {
  const response = await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) await throwApiError(response);
  return (await response.json()) as TeamRunRecord;
}

export function useTeamRun(runId: string | null, enabled = true) {
  return useQuery<TeamRunRecord>({
    queryKey: runId === null ? ["team-run"] : teamRunQueryKey(runId),
    queryFn: () => getTeamRun(runId as string),
    enabled: enabled && runId !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2_000 : false),
  });
}
