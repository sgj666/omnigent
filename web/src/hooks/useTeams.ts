import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTeam,
  getTeam,
  listTeamRuns,
  listTeams,
  updateTeam,
  type CreateTeamInput,
  type Team,
  type TeamRun,
  type UpdateTeamInput,
} from "@/lib/teamsApi";

export const teamsQueryKey = ["teams"] as const;
export const teamRunsQueryKey = (teamId: string) => ["team-runs", teamId] as const;

export function useTeams(enabled = true) {
  return useQuery({ queryKey: teamsQueryKey, queryFn: listTeams, enabled });
}

export function useTeam(teamId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["teams", teamId],
    queryFn: () => getTeam(teamId as string),
    enabled: enabled && teamId !== null,
  });
}

export function useTeamRuns(teamId: string | null, enabled = true) {
  return useQuery<TeamRun[]>({
    queryKey: teamId === null ? ["team-runs"] : teamRunsQueryKey(teamId),
    queryFn: () => listTeamRuns(teamId as string),
    enabled: enabled && teamId !== null,
  });
}

export function useCreateTeam() {
  const queryClient = useQueryClient();
  return useMutation<Team, Error, CreateTeamInput>({
    mutationFn: createTeam,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: teamsQueryKey });
    },
  });
}

export function useUpdateTeam(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation<Team, Error, UpdateTeamInput>({
    mutationFn: (input) => updateTeam(teamId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: teamsQueryKey });
      void queryClient.invalidateQueries({ queryKey: ["teams", teamId] });
    },
  });
}
