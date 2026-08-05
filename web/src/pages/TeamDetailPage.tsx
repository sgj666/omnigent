import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "@/lib/routing";
import { PageScroll } from "@/components/PageScroll";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateTeam, useTeam, useUpdateTeam } from "@/hooks/useTeams";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import type { TeamMember } from "@/lib/teamsApi";
import type { DraftMember } from "@/components/teams/AgentProfileList";
import { BotSurfacePanel, type BotSurfaceState } from "@/components/teams/BotSurfacePanel";
import { FeishuPairingPanel } from "@/components/teams/FeishuPairingPanel";
import { TeamForm, type TeamFormValues } from "@/components/teams/TeamForm";

const toDraft = (member: TeamMember, fallback: string): DraftMember => ({
  ...member,
  id: member.id ?? fallback,
  pairing: member.pairing ?? {},
  surface: member.surface ?? {},
});

export function TeamDetailPage() {
  const { teamId } = useParams<{ teamId: string }>();
  const isNew = !teamId || teamId === "new";
  const team = useTeam(isNew ? null : teamId);
  const workspaces = useWorkspaces();
  const create = useCreateTeam();
  const update = useUpdateTeam(teamId ?? "");
  const navigate = useNavigate();
  const [surface, setSurface] = useState<BotSurfaceState>({ status: "pending" });

  const initial = useMemo(() => {
    if (!team.data) return undefined;
    const members = [
      toDraft(team.data.coordinator, "coordinator"),
      ...team.data.workers.map((worker, index) => toDraft(worker, `worker-${index + 1}`)),
    ];
    return { name: team.data.name, members, workspaceId: "", executionMode: "auto" as const };
  }, [team.data]);

  if (!isNew && team.isLoading)
    return (
      <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground">
        Loading team…
      </div>
    );
  if (!isNew && (team.isError || !team.data))
    return (
      <div role="alert" className="p-8 text-sm text-destructive">
        Could not load this team.
      </div>
    );

  async function save(values: TeamFormValues) {
    const members = values.members.map(
      ({ id: _id, pairing, surface: memberSurface, ...member }) => ({
        ...member,
        pairing,
        surface: memberSurface,
      }),
    );
    if (isNew) {
      const created = await create.mutateAsync({ name: values.name, members });
      navigate(`/teams/${created.id}`);
    } else {
      await update.mutateAsync({ name: values.name, members });
    }
  }

  const coordinator = initial?.members.find((member) => member.role === "coordinator");
  return (
    <PageScroll contentClassName="mx-auto w-full max-w-5xl px-6 py-8" extraBottom="2.5rem">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/teams" className="text-sm text-muted-foreground hover:underline">
          ← Teams
        </Link>
        <h1 className="text-2xl font-semibold">
          {isNew ? "Create team" : `Edit ${team.data?.name ?? "team"}`}
        </h1>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader>
            <CardTitle>Team Builder</CardTitle>
          </CardHeader>
          <CardContent>
            <TeamForm
              initial={initial}
              workspaces={workspaces.data ?? []}
              onSubmit={save}
              submitting={create.isPending || update.isPending}
            />
          </CardContent>
        </Card>
        <div className="space-y-6">
          <FeishuPairingPanel
            pairing={coordinator?.pairing}
            onChange={() => setSurface((state) => ({ ...state, status: "ready" }))}
          />
          <BotSurfacePanel
            surface={(coordinator?.surface as BotSurfaceState | undefined) ?? surface}
            onReinitialize={async () => setSurface({ status: "ready" })}
          />
        </div>
      </div>
      {(create.isError || update.isError) && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {(create.error ?? update.error)?.message}
        </p>
      )}
    </PageScroll>
  );
}
