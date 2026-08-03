import { ExternalLink, GitCommitHorizontal, Inbox, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TeamRunRecord } from "@/hooks/useTeamRuns";

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function list(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown, fallback = "—"): string {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function formatTime(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  const date = new Date(typeof value === "number" && value < 10_000_000_000 ? value * 1000 : String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatMetric(value: unknown, suffix = ""): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "number") return `${value}${suffix}`;
  return `${String(value)}${suffix}`;
}

function formatPercent(value: unknown): string {
  if (typeof value === "number" && value >= 0 && value <= 1) return `${Math.round(value * 100)}%`;
  return formatMetric(value, "%");
}

function metric(metrics: JsonRecord, ...keys: string[]): unknown {
  for (const key of keys) if (metrics[key] !== undefined) return metrics[key];
  return undefined;
}

function Detail({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono text-xs" title={text(value)}>{text(value)}</dd>
    </div>
  );
}

function LogBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-48 overflow-auto rounded-md bg-muted/60 p-3 font-mono text-xs whitespace-pre-wrap">{String(value)}</pre>
    </div>
  );
}

export interface RunInspectorProps {
  run: TeamRunRecord;
}

export function RunInspector({ run }: RunInspectorProps) {
  const data = record(run);
  const workspace = record(data.workspace);
  const workspaceName = data.workspace_name ?? workspace.name ?? data.workspace_id;
  const tasks = list(data.tasks ?? data.task_dag ?? data.run_tasks);
  const attempts = [
    ...list(data.attempts),
    ...tasks.flatMap((task) => list(task.attempts).map((attempt) => ({ ...attempt, task_id: attempt.task_id ?? task.id }))),
  ];
  const events = list(data.events ?? data.ledger_events ?? data.parent_inbox_events);
  const inbox = list(data.parent_inbox ?? data.parentInbox);
  const artifacts = list(data.artifacts);
  const commits = list(data.commits);
  const metrics = record(data.evaluation ?? data.metrics ?? data.ledger_summary ?? data.evaluation_summary);
  const delivery = data.delivery_status ?? data.deliveryState ?? metric(metrics, "delivery_status", "delivery");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Run Inspector</CardTitle>
              <CardDescription className="mt-1 font-mono">{text(data.id ?? run.id)}</CardDescription>
            </div>
            <Badge variant={data.status === "failed" ? "destructive" : "outline"}>{text(data.status ?? run.status)}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Detail label="team" value={data.team_id ?? run.team_id} />
            <Detail label="source" value={data.source ?? run.source} />
            <Detail label="workspace (immutable)" value={workspaceName} />
            <Detail label="workspace id" value={data.workspace_id ?? run.workspace_id} />
          </dl>
          <p className="mt-4 rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-mono text-foreground">workspace: {text(workspaceName)}</span> · immutable for this run
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Evaluation summary</CardTitle><CardDescription>Aggregated from the Durable Ledger; chat messages are not used.</CardDescription></CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Detail label="completion rate" value={formatPercent(metric(metrics, "completion_rate", "completed_rate"))} />
            <Detail label="first-attempt success" value={formatPercent(metric(metrics, "first_success_rate", "first_attempt_success_rate"))} />
            <Detail label="retries" value={metric(metrics, "retry_count", "retries")} />
            <Detail label="human approvals" value={metric(metrics, "human_approval_count", "approvals")} />
            <Detail label="average stage time" value={formatMetric(metric(metrics, "average_stage_duration", "avg_stage_duration"), " ms")} />
            <Detail label="parallel utilisation" value={formatPercent(metric(metrics, "parallel_utilization", "parallel_utilisation"))} />
            <Detail label="resource consumption" value={metric(metrics, "resource_consumption", "tokens", "token_usage", "cost")} />
            <Detail label="delivery status" value={delivery} />
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Task DAG</CardTitle><CardDescription>Dependencies and current task state.</CardDescription></CardHeader>
        <CardContent>
          {tasks.length === 0 ? <p className="text-sm text-muted-foreground">No tasks recorded in the ledger.</p> : <div className="space-y-2">
            {tasks.map((task, index) => {
              const deps = task.depends_on ?? task.dependencies ?? task.parents;
              return <div key={text(task.id, String(index))} className="rounded-lg border border-border/70 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{text(task.title ?? task.name ?? task.id, `Task ${index + 1}`)}</span><Badge variant="outline">{text(task.status)}</Badge></div>
                <p className="mt-1 font-mono text-xs text-muted-foreground">{text(task.id)}</p>
                {Array.isArray(deps) && deps.length > 0 && <p className="mt-2 text-xs text-muted-foreground">depends on: {deps.map(String).join(", ")}</p>}
              </div>;
            })}
          </div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Attempts</CardTitle><CardDescription>Agent execution details and failure diagnostics.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          {attempts.length === 0 ? <p className="text-sm text-muted-foreground">No attempts recorded in the ledger.</p> : attempts.map((attempt, index) => {
            const failureCode = attempt.failure_code ?? record(attempt.failure).code;
            const retryAdvice = attempt.retry_suggestion ?? attempt.retry_recommendation ?? attempt.next_action;
            return <article key={text(attempt.id, String(index))} className="rounded-lg border border-border/70 p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">Attempt {index + 1} <span className="font-mono text-xs text-muted-foreground">{text(attempt.id)}</span></h3><Badge variant={attempt.status === "failed" ? "destructive" : "outline"}>{text(attempt.status)}</Badge></div>
              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Detail label="agent profile" value={attempt.agent_profile ?? attempt.agent_profile_id ?? attempt.profile} />
                <Detail label="worktree" value={attempt.worktree_path ?? attempt.worktree ?? attempt.workspace_lease_id} />
                <Detail label="stage" value={attempt.stage ?? attempt.phase} />
                <Detail label="tool calls" value={attempt.tool_calls ?? attempt.tools} />
                <Detail label="started" value={formatTime(attempt.started_at ?? attempt.start_time)} />
                <Detail label="ended" value={formatTime(attempt.finished_at ?? attempt.ended_at ?? attempt.end_time)} />
                <Detail label="retry count" value={attempt.retry_count ?? attempt.retries} />
                <Detail label="exit code" value={attempt.exit_code} />
              </dl>
              {failureCode !== undefined && <p className="mt-3 flex items-center gap-2 text-sm text-destructive"><TriangleAlert className="size-4" />failure_code: {String(failureCode)}</p>}
              {retryAdvice !== undefined && <p className="mt-2 text-xs text-muted-foreground">retry suggestion: {String(retryAdvice)}</p>}
              <div className="mt-3 grid gap-3 md:grid-cols-2"><LogBlock label="stdout" value={attempt.stdout} /><LogBlock label="stderr" value={attempt.stderr} /></div>
            </article>;
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Inbox className="size-4" />Coordinator Parent Inbox</CardTitle><CardDescription>Structured worker events delivered to the coordinator.</CardDescription></CardHeader>
        <CardContent>
          {[...inbox, ...events.filter((event) => String(event.type ?? event.event_type ?? "").toLowerCase().includes("inbox"))].length === 0 ? <p className="text-sm text-muted-foreground">No parent inbox events.</p> : <div className="space-y-2">{[...inbox, ...events.filter((event) => String(event.type ?? event.event_type ?? "").toLowerCase().includes("inbox"))].map((event, index) => <div key={text(event.id ?? event.event_id, String(index))} className="rounded-md bg-muted/40 p-3 text-xs"><div className="flex justify-between gap-3"><span className="font-medium">{text(event.type ?? event.event_type ?? event.kind)}</span><span className="text-muted-foreground">{formatTime(event.occurred_at ?? event.created_at)}</span></div><pre className="mt-2 whitespace-pre-wrap font-mono">{JSON.stringify(event.payload ?? event.message ?? event, null, 2)}</pre></div>)}</div>}
        </CardContent>
      </Card>

      {(commits.length > 0 || artifacts.length > 0) && <Card>
        <CardHeader><CardTitle>Commits &amp; artifacts</CardTitle><CardDescription>Outputs recorded by the ledger.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          {commits.length > 0 && <div><h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><GitCommitHorizontal className="size-4" />Commits</h3><ul className="space-y-1">{commits.map((commit, index) => <li key={text(commit.id ?? commit.sha, String(index))} className="font-mono text-xs">{text(commit.sha ?? commit.commit)} {text(commit.message, "")}</li>)}</ul></div>}
          {artifacts.length > 0 && <div><h3 className="mb-2 text-sm font-medium">Artifacts</h3><ul className="space-y-1">{artifacts.map((artifact, index) => { const href = artifact.url ?? artifact.href; return <li key={text(artifact.id ?? artifact.name, String(index))} className="text-sm">{typeof href === "string" ? <a className="inline-flex items-center gap-1 text-primary hover:underline" href={href}><ExternalLink className="size-3" />{text(artifact.name ?? artifact.path ?? href)}</a> : text(artifact.name ?? artifact.path)}</li>; })}</ul></div>}
        </CardContent>
      </Card>}
    </div>
  );
}
