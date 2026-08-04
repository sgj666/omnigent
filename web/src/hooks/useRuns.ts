import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import {
  getRunEvaluation,
  getRunInspector,
  refreshRunEvaluation,
  type RunEvaluationDto,
  type RunInspectorResponseDto,
} from "@/lib/runsApi";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

export const runQueryKey = (runId: string) => ["run", runId] as const;
export const runEvaluationQueryKey = (runId: string) => ["run", runId, "evaluation"] as const;

export function useRun(runId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const previous = useRef<{ runId: string; status: string } | null>(null);
  const runQuery = useQuery<RunInspectorResponseDto>({
    queryKey: runId === null ? ["run"] : runQueryKey(runId),
    queryFn: () => getRunInspector(runId as string),
    enabled: enabled && runId !== null,
    refetchInterval: (currentQuery) => {
      const status = currentQuery.state.data?.run.status;
      return status !== undefined && !TERMINAL_RUN_STATUSES.has(status) ? 2_000 : false;
    },
  });
  useEffect(() => {
    const status = runQuery.data?.run.status;
    if (runId === null || status === undefined) return;
    const prior = previous.current;
    if (
      prior?.runId === runId &&
      !TERMINAL_RUN_STATUSES.has(prior.status) &&
      TERMINAL_RUN_STATUSES.has(status)
    ) {
      void queryClient.refetchQueries({
        queryKey: runEvaluationQueryKey(runId),
        exact: true,
        type: "active",
      });
    }
    previous.current = { runId, status };
  }, [runQuery.data?.run.status, queryClient, runId]);
  return runQuery;
}

export function useRunEvaluation(runId: string | null, enabled = true) {
  return useQuery<RunEvaluationDto>({
    queryKey: runId === null ? ["run", "evaluation"] : runEvaluationQueryKey(runId),
    queryFn: () => getRunEvaluation(runId as string),
    enabled: enabled && runId !== null,
    retry: false,
  });
}

export function useRefreshRunEvaluation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: refreshRunEvaluation,
    onSuccess: (evaluation) => {
      queryClient.setQueryData(runEvaluationQueryKey(evaluation.run_id), evaluation);
    },
  });
}
