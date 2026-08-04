import { ExternalLink, Inbox, RefreshCw, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "@/lib/routing";
import type {
  RunEvaluationDto,
  RunInspectorAttemptDto,
  RunInspectorResponseDto,
} from "@/lib/runsApi";

function display(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function formatTime(value: number | null): string {
  if (value === null) return "—";
  return new Date(value * 1_000).toLocaleString();
}

function formatSeconds(value: number | null): string {
  return value === null ? "—" : `${value} s`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function attemptDuration(attempt: RunInspectorAttemptDto): number | null {
  if (attempt.started_at === null || attempt.completed_at === null) return null;
  return Math.max(0, attempt.completed_at - attempt.started_at);
}

function attemptOverlaps(attempts: RunInspectorAttemptDto[]): Map<string, number | null> {
  const overlaps = new Map<string, number | null>();
  const boundaries = new Map<number, { starts: string[]; ends: string[] }>();
  const boundary = (time: number) => {
    const existing = boundaries.get(time);
    if (existing) return existing;
    const created = { starts: [], ends: [] };
    boundaries.set(time, created);
    return created;
  };

  for (const attempt of attempts) {
    if (attempt.started_at === null || attempt.completed_at === null) {
      overlaps.set(attempt.id, null);
      continue;
    }
    overlaps.set(attempt.id, 0);
    if (attempt.completed_at <= attempt.started_at) continue;
    boundary(attempt.started_at).starts.push(attempt.id);
    boundary(attempt.completed_at).ends.push(attempt.id);
  }

  const active = new Set<string>();
  let previousTime: number | null = null;
  for (const [time, events] of [...boundaries.entries()].sort(([left], [right]) => left - right)) {
    if (previousTime !== null && active.size > 1) {
      const duration = time - previousTime;
      for (const attemptId of active) {
        overlaps.set(attemptId, (overlaps.get(attemptId) ?? 0) + duration);
      }
    }
    for (const attemptId of events.ends) active.delete(attemptId);
    for (const attemptId of events.starts) active.add(attemptId);
    previousTime = time;
  }
  return overlaps;
}

function safeArtifactHref(location: string): string | null {
  if (location.startsWith("/") && !location.startsWith("//") && !location.includes("\\")) {
    return location;
  }
  if (!/^https?:\/\//i.test(location)) return null;
  try {
    const url = new URL(location);
    return url.protocol === "http:" || url.protocol === "https:" ? location : null;
  } catch {
    return null;
  }
}

function Detail({ label, value }: { label: string; value: string | number | null | undefined }) {
  const rendered = display(value);
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words font-mono text-xs" title={rendered}>
        {rendered}
      </dd>
    </div>
  );
}

function statusVariant(status: string): "destructive" | "outline" {
  return status === "failed" ? "destructive" : "outline";
}

interface SafeEventPayloadDetail {
  label: "eventStatus" | "eventTimestamp" | "failureCode" | "responseId" | "outputCommit";
  value: string;
}

function safeEventPayloadDetails(payload: Record<string, unknown>): SafeEventPayloadDetail[] {
  const details: SafeEventPayloadDetail[] = [];
  const status = payload.status;
  if (typeof status === "string" && status) {
    details.push({ label: "eventStatus", value: status });
  }
  const occurredAt = payload.occurred_at;
  if (typeof occurredAt === "number" && Number.isFinite(occurredAt)) {
    details.push({ label: "eventTimestamp", value: formatTime(occurredAt) });
  }
  const references = [
    ["failure_code", "failureCode"],
    ["response_id", "responseId"],
    ["output_commit", "outputCommit"],
  ] as const;
  for (const [field, label] of references) {
    const value = payload[field];
    if (typeof value === "string" && value) details.push({ label, value });
  }
  return details;
}

export interface RunInspectorProps {
  inspector: RunInspectorResponseDto;
  evaluation?: RunEvaluationDto;
  evaluationError?: string | null;
  evaluationRefreshing?: boolean;
  onRefreshEvaluation?: () => void;
}

export function RunInspector({
  inspector,
  evaluation,
  evaluationError = null,
  evaluationRefreshing = false,
  onRefreshEvaluation,
}: RunInspectorProps) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent.runInspector" });
  const { run, agent_snapshot: snapshot, workspace } = inspector;
  const overlapByAttemptId = attemptOverlaps(inspector.attempts);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t("title")}</CardTitle>
              <CardDescription className="mt-1 font-mono">{run.id}</CardDescription>
            </div>
            <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Detail label={t("labels.source")} value={run.source} />
            <Detail label={t("labels.actor")} value={run.actor_id} />
            <Detail label={t("labels.authScope")} value={run.auth_scope} />
            <Detail label={t("labels.workspaceId")} value={run.workspace_id} />
            <Detail label={t("labels.rootSessionId")} value={inspector.root_session_id} />
            <Detail label={t("labels.sourceEventId")} value={run.source_event_id} />
            <Detail label={t("labels.created")} value={formatTime(run.created_at)} />
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("snapshot")}</CardTitle>
          <CardDescription>{t("snapshotDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {snapshot ? (
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Detail label={t("labels.agentId")} value={snapshot.id} />
              <Detail label={t("labels.bundleVersion")} value={snapshot.bundle_version} />
              <Detail label={t("labels.bundleDigest")} value={snapshot.bundle_digest} />
              <Detail label={t("labels.bundleLocation")} value={snapshot.bundle_location} />
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noSnapshot")}</p>
          )}
          {workspace ? (
            <div className="rounded-lg border border-border/70 p-3">
              <dl className="grid gap-4 sm:grid-cols-2">
                <Detail label={t("labels.workspaceId")} value={workspace.id} />
                <Detail label={t("labels.rootPath")} value={workspace.root_path} />
              </dl>
              <h3 className="mt-4 text-sm font-medium">{t("repositories")}</h3>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {workspace.repositories.map((repository) => (
                  <li key={repository.id} className="rounded-md bg-muted/40 p-2 text-xs">
                    <span className="font-medium">{repository.name}</span>
                    <span className="ml-2 font-mono text-muted-foreground">{repository.path}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noWorkspace")}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("sessions")}</CardTitle>
          <CardDescription>{t("sessionsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {inspector.sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noSessions")}</p>
          ) : (
            <ul className="space-y-2">
              {inspector.sessions.map((session) => (
                <li
                  key={session.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border/70 p-3"
                >
                  <Link
                    className="font-mono text-sm text-primary hover:underline"
                    to={`/c/${session.id}`}
                  >
                    {session.id}
                  </Link>
                  <Badge variant="outline">
                    {session.kind === "root" ? t("root") : t("child")}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("taskDag")}</CardTitle>
          <CardDescription>{t("taskDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {inspector.tasks.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noTasks")}</p>
          ) : (
            <div className="space-y-2">
              {inspector.tasks.map((task) => {
                const dependencies = inspector.dependencies
                  .filter((dependency) => dependency.task_id === task.id)
                  .map((dependency) => dependency.depends_on_task_id);
                return (
                  <article key={task.id} className="rounded-lg border border-border/70 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-medium">{task.title}</h3>
                      <Badge variant={statusVariant(task.status)}>{task.status}</Badge>
                    </div>
                    <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Detail label={t("labels.taskId")} value={task.id} />
                      <Detail label={t("labels.dispatchTitle")} value={task.dispatch_title} />
                      <Detail label={t("labels.purpose")} value={task.purpose} />
                      <Detail label={t("labels.childSessionId")} value={task.child_session_id} />
                    </dl>
                    {dependencies.length > 0 && (
                      <p className="mt-3 text-xs text-muted-foreground">
                        {t("dependsOn", { dependencies: dependencies.join(", ") })}
                      </p>
                    )}
                  </article>
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
        <CardContent>
          {inspector.attempts.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noAttempts")}</p>
          ) : (
            <div className="space-y-3">
              {inspector.attempts.map((attempt) => (
                <article key={attempt.id} className="rounded-lg border border-border/70 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-mono text-sm">{attempt.id}</h3>
                    <Badge variant={statusVariant(attempt.status)}>{attempt.status}</Badge>
                  </div>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Detail label={t("labels.taskId")} value={attempt.task_id} />
                    <Detail label={t("labels.worker")} value={attempt.worker_name} />
                    <Detail label={t("labels.purpose")} value={attempt.purpose} />
                    <Detail label={t("labels.workerConfig")} value={attempt.worker_config_path} />
                    <Detail label={t("labels.harness")} value={attempt.harness} />
                    <Detail label={t("labels.model")} value={attempt.model} />
                    <Detail label={t("labels.started")} value={formatTime(attempt.started_at)} />
                    <Detail
                      label={t("labels.completed")}
                      value={formatTime(attempt.completed_at)}
                    />
                    <Detail
                      label={t("labels.duration")}
                      value={formatSeconds(attemptDuration(attempt))}
                    />
                    <Detail
                      label={t("labels.parallelOverlap")}
                      value={formatSeconds(overlapByAttemptId.get(attempt.id) ?? null)}
                    />
                    <Detail label={t("labels.childSessionId")} value={attempt.child_session_id} />
                  </dl>
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("leases")}</CardTitle>
          <CardDescription>{t("leasesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {inspector.leases.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noLeases")}</p>
          ) : (
            <div className="space-y-3">
              {inspector.leases.map((lease) => (
                <article key={lease.id} className="rounded-lg border border-border/70 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-sm">{lease.id}</span>
                    <Badge variant="outline">{lease.status}</Badge>
                  </div>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Detail label={t("labels.worktree")} value={lease.worktree_path} />
                    <Detail label={t("labels.branch")} value={lease.branch} />
                    <Detail label={t("labels.baseCommit")} value={lease.base_commit} />
                    <Detail label={t("labels.outputCommit")} value={lease.output_commit} />
                    <Detail label={t("labels.host")} value={lease.host_id} />
                    <Detail label={t("labels.repositoryId")} value={lease.repository_id} />
                    <Detail label={t("labels.owner")} value={lease.owner_id} />
                    <Detail label={t("labels.childSessionId")} value={lease.child_session_id} />
                  </dl>
                </article>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TriangleAlert className="size-4" />
            {t("failures")}
          </CardTitle>
          <CardDescription>{t("failuresDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {inspector.failures.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noFailures")}</p>
          ) : (
            <ul className="space-y-2">
              {inspector.failures.map((failure) => (
                <li
                  key={`${failure.attempt_id ?? "run"}-${failure.code}-${failure.message}`}
                  className="rounded-lg border border-destructive/30 p-3"
                >
                  <p className="font-mono text-xs text-destructive">{failure.code}</p>
                  <p className="mt-1 text-sm">{failure.message}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {t("attemptReference", { id: display(failure.attempt_id) })}
                  </p>
                </li>
              ))}
            </ul>
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
          {inspector.events.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noInbox")}</p>
          ) : (
            <div className="space-y-2">
              {inspector.events.map((event) => {
                const safePayloadDetails = safeEventPayloadDetails(event.payload);
                return (
                  <article
                    key={`${event.source}:${event.source_event_id}`}
                    className="rounded-lg border border-border/70 p-3"
                  >
                    <h3 className="font-medium">{event.event_type}</h3>
                    <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Detail label={t("labels.eventSource")} value={event.source} />
                      <Detail label={t("labels.sourceEventId")} value={event.source_event_id} />
                      <Detail label={t("labels.taskId")} value={event.task_id} />
                      <Detail label={t("labels.attemptId")} value={event.attempt_id} />
                      <Detail label={t("labels.sessionId")} value={event.session_id} />
                      <Detail
                        label={t("labels.conversationItemId")}
                        value={event.conversation_item_id}
                      />
                      {safePayloadDetails.map((detail) => (
                        <Detail
                          key={detail.label}
                          label={t(`labels.${detail.label}`)}
                          value={detail.value}
                        />
                      ))}
                    </dl>
                  </article>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("references")}</CardTitle>
          <CardDescription>{t("referencesDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium">{t("logs")}</h3>
            {inspector.log_references.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">{t("noLogs")}</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {inspector.log_references.map((reference) => (
                  <li key={`${reference.session_id}-${reference.href}`}>
                    <a
                      className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                      href={reference.href}
                    >
                      <ExternalLink className="size-3" />
                      {t("logLink", { sessionId: reference.session_id })}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3 className="text-sm font-medium">{t("artifacts")}</h3>
            {inspector.artifact_references.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">{t("noArtifacts")}</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {inspector.artifact_references.map((artifact) => {
                  const href = safeArtifactHref(artifact.location);
                  return (
                    <li key={artifact.id}>
                      {href ? (
                        <a
                          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                          href={href}
                        >
                          <ExternalLink className="size-3" />
                          {artifact.name}
                        </a>
                      ) : (
                        <span className="text-sm">{artifact.name}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t("evaluation")}</CardTitle>
              <CardDescription>{t("evaluationDescription")}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {evaluation && (
                <Badge variant="outline">{t(`evaluationStatus.${evaluation.status}`)}</Badge>
              )}
              {onRefreshEvaluation && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={evaluationRefreshing}
                  onClick={onRefreshEvaluation}
                >
                  <RefreshCw className={evaluationRefreshing ? "animate-spin" : undefined} />
                  {evaluationRefreshing ? t("refreshingEvaluation") : t("refreshEvaluation")}
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {evaluationError && (
            <p role="alert" className="mb-4 text-sm text-destructive">
              {t("evaluationError", { message: evaluationError })}
            </p>
          )}
          {!evaluation ? (
            <p className="text-sm text-muted-foreground">{t("noEvaluation")}</p>
          ) : (
            <div className="space-y-5">
              <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Detail
                  label={t("labels.completionRate")}
                  value={formatPercent(evaluation.metrics.task_completion_rate)}
                />
                <Detail
                  label={t("labels.attemptSuccess")}
                  value={t("successValue", {
                    value: formatPercent(evaluation.metrics.attempt_success_rate),
                  })}
                />
                <Detail label={t("labels.retries")} value={evaluation.metrics.retry_count} />
                <Detail label={t("labels.blocked")} value={evaluation.metrics.blocked_count} />
                <Detail
                  label={t("labels.blockedDuration")}
                  value={formatSeconds(evaluation.metrics.blocked_duration_seconds)}
                />
                <Detail
                  label={t("labels.parallelOverlap")}
                  value={formatSeconds(evaluation.metrics.parallel_overlap_seconds)}
                />
                <Detail
                  label={t("labels.maxConcurrency")}
                  value={evaluation.metrics.max_concurrency}
                />
                <Detail
                  label={t("labels.workerDuration")}
                  value={formatSeconds(evaluation.metrics.worker_duration_seconds)}
                />
                <Detail
                  label={t("labels.parentInboxLatency")}
                  value={formatSeconds(evaluation.metrics.parent_inbox_latency_seconds)}
                />
                <Detail
                  label={t("labels.parentInboxSamples")}
                  value={evaluation.metrics.parent_inbox_latency_samples}
                />
              </dl>
              <div>
                <h3 className="text-sm font-medium">{t("workers")}</h3>
                {evaluation.workers.length === 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">{t("noWorkers")}</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {evaluation.workers.map((worker) => (
                      <article key={worker.worker_name} className="rounded-lg bg-muted/40 p-3">
                        <h4 className="font-medium">
                          {t("workerValue", { name: worker.worker_name })}
                        </h4>
                        <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <Detail label={t("labels.tasks")} value={worker.task_count} />
                          <Detail label={t("labels.attempts")} value={worker.attempt_count} />
                          <Detail label={t("labels.successes")} value={worker.success_count} />
                          <Detail
                            label={t("labels.duration")}
                            value={formatSeconds(worker.duration_seconds)}
                          />
                        </dl>
                      </article>
                    ))}
                  </div>
                )}
              </div>
              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <h3 className="text-sm font-medium">{t("evidenceCounts")}</h3>
                  <dl className="mt-2 grid grid-cols-2 gap-3">
                    {Object.entries(evaluation.metrics.evidence_counts).map(([kind, count]) => (
                      <Detail key={kind} label={t(`evidence.${kind}`)} value={count} />
                    ))}
                  </dl>
                </div>
                <div>
                  <h3 className="text-sm font-medium">{t("evidenceReferences")}</h3>
                  <ul className="mt-2 space-y-1 font-mono text-xs">
                    {evaluation.evidence_refs.map((reference) => (
                      <li key={reference}>{reference}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
