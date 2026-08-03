import { Link, useParams } from "@/lib/routing";
import { PageScroll } from "@/components/PageScroll";
import { RunInspector } from "@/components/runs/RunInspector";
import { useTeamRun } from "@/hooks/useTeamRuns";

export function RunInspectorPage() {
  const { runId } = useParams<{ runId: string }>();
  const run = useTeamRun(runId ?? null);

  if (!runId) return <div role="alert" className="p-8 text-sm text-destructive">Run id is required.</div>;
  if (run.isLoading) return <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground">Loading run…</div>;
  if (run.isError) return <div role="alert" className="p-8 text-sm text-destructive">Could not load run: {run.error.message}</div>;
  if (!run.data) return <div role="alert" className="p-8 text-sm text-destructive">Run not found.</div>;

  return (
    <PageScroll contentClassName="mx-auto w-full max-w-6xl px-6 py-8" extraBottom="2.5rem">
      <div className="mb-6 flex items-center gap-3">
        <Link to={run.data.team_id ? `/teams/${run.data.team_id}` : "/teams"} className="text-sm text-muted-foreground hover:underline">← Team</Link>
        <h1 className="text-2xl font-semibold">Run {run.data.id}</h1>
      </div>
      <RunInspector run={run.data} />
    </PageScroll>
  );
}

export default RunInspectorPage;
