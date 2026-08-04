import { ExternalLink, GitCommitHorizontal, Inbox, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
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
  const date = new Date(
    typeof value === "number" && value < 10_000_000_000 ? value * 1000 : String(value),
  );
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatMetric(value: unknown, suffix = ""): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "number") return `${value}${suffix}`;
  return `${String(value)}${suffix}`;
}

function duration(start: unknown, end: unknown, explicit: unknown): string {
  if (typeof explicit === "number") return `${Math.round(explicit)} ms`;
  if (start == null || end == null) return "—";
  const startMs = new Date(
    typeof start === "number" && start < 10_000_000_000 ? start * 1000 : String(start),
  ).getTime();
  const endMs = new Date(
    typeof end === "number" && end < 10_000_000_000 ? end * 1000 : String(end),
  ).getTime();
  return Number.isNaN(startMs) || Number.isNaN(endMs) ? "—" : `${Math.max(0, endMs - startMs)} ms`;
}

function shortDigest(value: unknown): string {
  return typeof value === "string" ? value.replace(/^sha256:/, "").slice(0, 12) : "—";
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
      <dd className="truncate font-mono text-xs" title={text(value)}>
        {text(value)}
      </dd>
    </div>
  );
}

function LogBlock({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-48 overflow-auto rounded-md bg-muted/60 p-3 font-mono text-xs whitespace-pre-wrap">
        {String(value)}
      </pre>
    </div>
  );
}

export interface RunInspectorProps {
  run: TeamRunRecord;
}

export function RunInspector({ run }: RunInspectorProps) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent.runInspector" });
  const data = record(run);
  const workspace = record(data.workspace);
  const workspaceName = data.workspace_name ?? workspace.name ?? data.workspace_id;
  const tasks = list(data.tasks ?? data.task_dag ?? data.run_tasks);
  const attempts = [
    ...list(data.attempts),
    ...tasks.flatMap((task) =>
      list(task.attempts).map((attempt): JsonRecord => ({
        ...attempt,
        task_id: attempt.task_id ?? task.id,
      })),
    ),
  ];
  const rootSession = record(data.root_session ?? data.rootSession);
  const childSessions = list(data.child_sessions ?? data.childSessions ?? data.sessions);
  const sessions: JsonRecord[] = [
    ...(Object.keys(rootSession).length ? [{ ...rootSession, session_role: "root" }] : []),
    ...childSessions.map((session) => ({ ...session, session_role: "child" })),
  ];
  const events = list(data.events ?? data.ledger_events ?? data.parent_inbox_events);
  const inbox = list(data.parent_inbox ?? data.parentInbox);
  const artifacts = list(data.artifacts);
  const commits = list(data.commits);
  const metrics = record(
    data.evaluation ?? data.metrics ?? data.ledger_summary ?? data.evaluation_summary,
  );
  const delivery =
    data.delivery_status ?? data.deliveryState ?? metric(metrics, "delivery_status", "delivery");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t("title")}</CardTitle>
              <CardDescription className="mt-1 font-mono">
                {text(data.id ?? run.id)}
              </CardDescription>
            </div>
            <Badge variant={data.status === "failed" ? "destructive" : "outline"}>
              {text(data.status ?? run.status)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Detail label={t("labels.team")} value={data.team_id ?? run.team_id} />
            <Detail label={t("labels.source")} value={data.source ?? run.source} />
            <Detail label={t("labels.workspace")} value={workspaceName} />
            <Detail label={t("labels.workspaceId")} value={data.workspace_id ?? run.workspace_id} />
          </dl>
          <p className="mt-4 rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-mono text-foreground">workspace: {text(workspaceName)}</span> ·{" "}
            {t("workspaceImmutable")}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <Badge variant="outline">
              {t("bundleVersionValue", {
                version: text(data.bundle_version ?? data.agent_bundle_version),
              })}
            </Badge>
            <Badge variant="outline" title={text(data.bundle_digest ?? data.agent_bundle_digest)}>
              {shortDigest(data.bundle_digest ?? data.agent_bundle_digest)}
            </Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("sessions")}</CardTitle>
          <CardDescription>{t("sessionsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noSessions")}</p>
          ) : (
            <div className="space-y-2">
              {sessions.map((session, index) => (
                <div
                  key={text(session.id ?? session.session_id, String(index))}
                  className="rounded-lg border border-border/70 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="mr-2 text-xs font-medium text-muted-foreground">
                        {session.session_role === "root" ? t("root") : t("child")}
                      </span>
                      <span className="font-medium">
                        {text(session.title ?? session.worker_title ?? session.agent_name)}
                      </span>
                    </div>
                    <Badge variant={session.status === "failed" ? "destructive" : "outline"}>
                      {text(session.status)}
                    </Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs text-muted-foreground">
                    <span>{text(session.id ?? session.session_id)}</span>
                    <span>
                      {t("labels.duration")}:{" "}
                      {duration(session.started_at, session.finished_at, session.duration_ms)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("evaluation")}</CardTitle>
          <CardDescription>{t("evaluationDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Detail
              label={t("labels.completionRate")}
              value={formatPercent(metric(metrics, "completion_rate", "completed_rate"))}
            />
            <Detail
              label={t("labels.firstSuccess")}
              value={formatPercent(
                metric(metrics, "first_success_rate", "first_attempt_success_rate"),
              )}
            />
            <Detail label={t("labels.retries")} value={metric(metrics, "retry_count", "retries")} />
            <Detail
              label={t("labels.approvals")}
              value={metric(metrics, "human_approval_count", "approvals")}
            />
            <Detail
              label={t("labels.averageStage")}
              value={formatMetric(
                metric(metrics, "average_stage_duration", "avg_stage_duration"),
                " ms",
              )}
            />
            <Detail
              label={t("labels.parallel")}
              value={formatPercent(metric(metrics, "parallel_utilization", "parallel_utilisation"))}
            />
            <Detail
              label={t("labels.resources")}
              value={metric(metrics, "resource_consumption", "tokens", "token_usage", "cost")}
            />
            <Detail label={t("labels.delivery")} value={delivery} />
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("taskDag")}</CardTitle>
          <CardDescription>{t("taskDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {tasks.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noTasks")}</p>
          ) : (
            <div className="space-y-2">
              {tasks.map((task, index) => {
                const deps = task.depends_on ?? task.dependencies ?? task.parents;
                return (
                  <div
                    key={text(task.id, String(index))}
                    className="rounded-lg border border-border/70 p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">
                        {text(task.title ?? task.name ?? task.id, `Task ${index + 1}`)}
                      </span>
                      <Badge variant="outline">{text(task.status)}</Badge>
                    </div>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">{text(task.id)}</p>
                    {Array.isArray(deps) && deps.length > 0 && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        {t("dependsOn", { dependencies: deps.map(String).join(", ") })}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("attempts")}</CardTitle>
          <CardDescription>{t("attemptsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {attempts.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noAttempts")}</p>
          ) : (
            attempts.map((attempt, index) => {
              const failureCode = attempt.failure_code ?? record(attempt.failure).code;
              const failureReason =
                attempt.failure_reason ?? record(attempt.failure).message ?? attempt.error;
              const retryAdvice =
                attempt.retry_suggestion ?? attempt.retry_recommendation ?? attempt.next_action;
              return (
                <article
                  key={text(attempt.id, String(index))}
                  className="rounded-lg border border-border/70 p-4"
                >
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-medium">
                      {text(
                        attempt.worker_title ?? attempt.title,
                        t("attemptNumber", { number: index + 1 }),
                      )}{" "}
                      <span className="font-mono text-xs text-muted-foreground">
                        {text(attempt.id)}
                      </span>
                    </h3>
                    <Badge variant={attempt.status === "failed" ? "destructive" : "outline"}>
                      {text(attempt.status)}
                    </Badge>
                  </div>
                  <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Detail
                      label={t("labels.agentProfile")}
                      value={attempt.agent_profile ?? attempt.agent_profile_id ?? attempt.profile}
                    />
                    <Detail
                      label={t("labels.worktree")}
                      value={
                        attempt.worktree_path ?? attempt.worktree ?? attempt.workspace_lease_id
                      }
                    />
                    <Detail label={t("labels.stage")} value={attempt.stage ?? attempt.phase} />
                    <Detail
                      label={t("labels.toolCalls")}
                      value={attempt.tool_calls ?? attempt.tools}
                    />
                    <Detail
                      label={t("labels.started")}
                      value={formatTime(attempt.started_at ?? attempt.start_time)}
                    />
                    <Detail
                      label={t("labels.ended")}
                      value={formatTime(
                        attempt.finished_at ?? attempt.ended_at ?? attempt.end_time,
                      )}
                    />
                    <Detail
                      label={t("labels.duration")}
                      value={duration(
                        attempt.started_at ?? attempt.start_time,
                        attempt.finished_at ?? attempt.ended_at ?? attempt.end_time,
                        attempt.duration_ms,
                      )}
                    />
                    <Detail
                      label={t("labels.retryCount")}
                      value={attempt.retry_count ?? attempt.retries}
                    />
                    <Detail label={t("labels.exitCode")} value={attempt.exit_code} />
                  </dl>
                  {failureCode !== undefined && (
                    <p className="mt-3 flex items-center gap-2 text-sm text-destructive">
                      <TriangleAlert className="size-4" />
                      {t("failureCode", { code: String(failureCode) })}
                    </p>
                  )}
                  {failureReason !== undefined && (
                    <p className="mt-2 text-sm text-destructive">{String(failureReason)}</p>
                  )}
                  {retryAdvice !== undefined && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {t("retrySuggestion", { advice: String(retryAdvice) })}
                    </p>
                  )}
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <LogBlock label={t("labels.stdout")} value={attempt.stdout} />
                    <LogBlock label={t("labels.stderr")} value={attempt.stderr} />
                  </div>
                </article>
              );
            })
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Inbox className="size-4" />
            {t("parentInbox")}
          </CardTitle>
          <CardDescription>{t("parentInboxDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {[
            ...inbox,
            ...events.filter((event) =>
              String(event.type ?? event.event_type ?? "")
                .toLowerCase()
                .includes("inbox"),
            ),
          ].length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noInbox")}</p>
          ) : (
            <div className="space-y-2">
              {[
                ...inbox,
                ...events.filter((event) =>
                  String(event.type ?? event.event_type ?? "")
                    .toLowerCase()
                    .includes("inbox"),
                ),
              ].map((event, index) => (
                <div
                  key={text(event.id ?? event.event_id, String(index))}
                  className="rounded-md bg-muted/40 p-3 text-xs"
                >
                  <div className="flex justify-between gap-3">
                    <span className="font-medium">
                      {text(event.type ?? event.event_type ?? event.kind)}
                    </span>
                    <span className="text-muted-foreground">
                      {formatTime(event.occurred_at ?? event.created_at)}
                    </span>
                  </div>
                  <pre className="mt-2 whitespace-pre-wrap font-mono">
                    {JSON.stringify(event.payload ?? event.message ?? event, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {(commits.length > 0 || artifacts.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>{t("outputs")}</CardTitle>
            <CardDescription>{t("outputsDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {commits.length > 0 && (
              <div>
                <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <GitCommitHorizontal className="size-4" />
                  {t("commits")}
                </h3>
                <ul className="space-y-1">
                  {commits.map((commit, index) => (
                    <li
                      key={text(commit.id ?? commit.sha, String(index))}
                      className="font-mono text-xs"
                    >
                      {text(commit.sha ?? commit.commit)} {text(commit.message, "")}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {artifacts.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium">{t("artifacts")}</h3>
                <ul className="space-y-1">
                  {artifacts.map((artifact, index) => {
                    const href = artifact.url ?? artifact.href;
                    return (
                      <li
                        key={text(artifact.id ?? artifact.name, String(index))}
                        className="text-sm"
                      >
                        {typeof href === "string" ? (
                          <a
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                            href={href}
                          >
                            <ExternalLink className="size-3" />
                            {text(artifact.name ?? artifact.path ?? href)}
                          </a>
                        ) : (
                          text(artifact.name ?? artifact.path)
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
