import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckSquare2Icon,
  ExternalLinkIcon,
  PlayIcon,
  RotateCcwIcon,
  SquareIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { PageBackButton } from "@/components/PageBackButton";
import { PageScroll } from "@/components/PageScroll";
import { CollectionState, StatusBadge } from "@/components/collection";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAvailableAgents } from "@/hooks/useAvailableAgents";
import { useHosts } from "@/hooks/useHosts";
import { useProjectConfig, useProjects } from "@/hooks/useConversations";
import { TASK_STATES, type TaskState } from "@/lib/workLifecycle";
import {
  WORK_ITEM_PRIORITIES,
  cancelWorkItemRun,
  createWorkItemRun,
  getWorkItem,
  listWorkItemRuns,
  updateWorkItem,
  type CreateWorkItemRunInput,
  type WorkItemPriority,
  type WorkItemRun,
} from "@/lib/workItemsApi";
import { Link, useParams } from "@/lib/routing";

function timestamp(value: number | null, language: string): string {
  if (value == null) return "—";
  return new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value * 1000),
  );
}

export function TaskDetailPage() {
  const { t, i18n } = useTranslation("management");
  const { taskId = "" } = useParams<{ taskId: string }>();
  const queryClient = useQueryClient();
  const projects = useProjects();
  const agents = useAvailableAgents();
  const task = useQuery({
    queryKey: ["work-items", taskId],
    queryFn: () => getWorkItem(taskId),
    enabled: Boolean(taskId),
    retry: false,
  });
  const runs = useQuery({
    queryKey: ["work-items", taskId, "runs"],
    queryFn: () => listWorkItemRuns(taskId),
    enabled: Boolean(taskId),
    retry: false,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((run) => ["queued", "running", "waiting"].includes(run.state))
        ? 2_000
        : false,
  });
  const projectConfig = useProjectConfig(task.data?.project_id ?? null);
  const hosts = useHosts();
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [runtimeId, setRuntimeId] = useState("");
  const [workspace, setWorkspace] = useState("");
  const mutation = useMutation({
    mutationFn: ({ field, value }: { field: "state" | "priority"; value: string }) => {
      if (!task.data) throw new Error("Task unavailable");
      return updateWorkItem(task.data.id, {
        expected_version: task.data.version,
        [field]: value,
      });
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["work-items", taskId], updated);
      void queryClient.invalidateQueries({ queryKey: ["work-items"], exact: true });
    },
  });
  const runMutation = useMutation({
    mutationFn: (input: CreateWorkItemRunInput) => createWorkItemRun(taskId, input),
    onSuccess: () => {
      setRunDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["work-items", taskId, "runs"] });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: (runId: string) => cancelWorkItemRun(taskId, runId),
    onSuccess: (updated) => {
      queryClient.setQueryData<WorkItemRun[]>(["work-items", taskId, "runs"], (current) =>
        current?.map((run) => (run.id === updated.id ? updated : run)),
      );
    },
  });

  const assignedAgent = agents.data?.find(
    (candidate) => candidate.id === task.data?.assignee_agent_id,
  );
  const availableHosts = useMemo(
    () =>
      (hosts.data ?? []).filter((host) => {
        if (host.status !== "online") return false;
        const harness = assignedAgent?.harness;
        if (!harness) return true;
        const readiness = host.configured_harnesses?.[harness];
        return readiness === undefined || readiness === true;
      }),
    [assignedAgent?.harness, hosts.data],
  );

  useEffect(() => {
    if (runtimeId && availableHosts.some((host) => host.host_id === runtimeId)) return;
    const preferred = projectConfig.data?.host_id;
    setRuntimeId(
      availableHosts.find((host) => host.host_id === preferred)?.host_id ??
        availableHosts[0]?.host_id ??
        "",
    );
  }, [availableHosts, projectConfig.data?.host_id, runtimeId]);

  useEffect(() => {
    if (!workspace && projectConfig.data?.workspace) {
      setWorkspace(projectConfig.data.workspace);
    }
  }, [projectConfig.data?.workspace, workspace]);

  if (task.isLoading || projects.isLoading || agents.isLoading) {
    return <CollectionState state="loading" title={t("tasks.detail.loading")} />;
  }
  if (task.isError || projects.isError || agents.isError || !task.data) {
    return <CollectionState state="error" title={t("tasks.detail.notFound")} />;
  }

  const item = task.data;
  const projectName = projects.data?.find((project) => project.id === item.project_id)?.name;
  const agentName =
    assignedAgent?.display_name ||
    assignedAgent?.name ||
    (item.assignee_agent_id
      ? t("tasks.detail.deletedAssignee", { id: item.assignee_agent_id.slice(0, 8) })
      : undefined);

  return (
    <PageScroll
      contentClassName="px-6"
      maxWidthClassName="max-w-6xl"
      data-testid="task-detail-page"
    >
      <PageBackButton fallbackTo="/tasks">{t("tasks.detail.back")}</PageBackButton>
      <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
              <CheckSquare2Icon className="size-4" />
            </span>
            <h1 className="truncate font-heading text-2xl font-semibold">{item.title}</h1>
          </div>
          {item.description && (
            <p className="mt-3 max-w-3xl whitespace-pre-wrap text-sm text-muted-foreground">
              {item.description}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={!item.assignee_agent_id}
            onClick={() => setRunDialogOpen(true)}
          >
            <PlayIcon />
            {t("tasks.detail.startRun")}
          </Button>
          <label className="space-y-1 text-xs text-muted-foreground">
            <span className="sr-only">{t("tasks.columns.state")}</span>
            <select
              aria-label={t("tasks.columns.state")}
              value={item.state}
              disabled={mutation.isPending}
              onChange={(event) =>
                mutation.mutate({ field: "state", value: event.target.value as TaskState })
              }
              className="h-8 rounded-lg border bg-background px-2 text-sm text-foreground"
            >
              {TASK_STATES.map((state) => (
                <option key={state} value={state}>
                  {t(`tasks.states.${state}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">
            <span className="sr-only">{t("tasks.columns.priority")}</span>
            <select
              aria-label={t("tasks.columns.priority")}
              value={item.priority}
              disabled={mutation.isPending}
              onChange={(event) =>
                mutation.mutate({
                  field: "priority",
                  value: event.target.value as WorkItemPriority,
                })
              }
              className="h-8 rounded-lg border bg-background px-2 text-sm text-foreground"
            >
              {WORK_ITEM_PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {t(`tasks.priorities.${priority}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {mutation.isError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {mutation.error.message}
        </p>
      )}

      <div className="mt-8 grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>{t("tasks.detail.runsTitle")}</CardTitle>
            <CardDescription>{t("tasks.detail.runsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <CollectionState state="loading" title={t("tasks.detail.runsLoading")} />
            ) : runs.isError ? (
              <CollectionState
                state="error"
                title={t("tasks.detail.runsError")}
                action={
                  <button
                    type="button"
                    className="text-sm font-medium text-primary"
                    onClick={() => void runs.refetch()}
                  >
                    {t("common.retry")}
                  </button>
                }
              />
            ) : runs.data?.length === 0 ? (
              <CollectionState
                state="empty"
                title={t("tasks.detail.noRuns")}
                description={t("tasks.detail.noRunsDescription")}
              />
            ) : (
              <div className="space-y-3">
                {runs.data?.map((run) => {
                  const runtimeName =
                    hosts.data?.find((host) => host.host_id === run.runtime_id)?.name ??
                    run.runtime_id;
                  const active = ["queued", "running", "waiting"].includes(run.state);
                  return (
                    <div
                      key={run.id}
                      id={`run-${run.id}`}
                      className="scroll-mt-24 rounded-xl border bg-muted/20 p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge
                              tone={
                                run.state === "succeeded"
                                  ? "success"
                                  : run.state === "failed"
                                    ? "danger"
                                    : run.state === "waiting"
                                      ? "warning"
                                      : "neutral"
                              }
                            >
                              {t(`tasks.detail.runStates.${run.state}`)}
                            </StatusBadge>
                            <span className="text-xs text-muted-foreground">
                              {t(`tasks.detail.runTriggers.${run.trigger}`)}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {timestamp(run.queued_at, i18n.language)}
                            </span>
                          </div>
                          <p className="mt-2 text-sm font-medium">{runtimeName}</p>
                          <p className="mt-0.5 break-all font-mono text-xs text-muted-foreground">
                            {run.workspace}
                          </p>
                          {run.failure && (
                            <p role="alert" className="mt-2 text-sm text-destructive">
                              {run.failure.message}
                            </p>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {run.session_id && (
                            <Button asChild variant="outline" size="sm">
                              <Link to={`/c/${run.session_id}`}>
                                <ExternalLinkIcon />
                                {t("tasks.detail.openSession")}
                              </Link>
                            </Button>
                          )}
                          {active && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              loading={cancelMutation.isPending}
                              onClick={() => cancelMutation.mutate(run.id)}
                            >
                              <SquareIcon />
                              {t("tasks.detail.cancelRun")}
                            </Button>
                          )}
                          {["failed", "cancelled"].includes(run.state) && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              loading={runMutation.isPending}
                              onClick={() =>
                                runMutation.mutate({
                                  runtime_id: run.runtime_id,
                                  workspace: run.workspace,
                                  retry_of_run_id: run.id,
                                })
                              }
                            >
                              <RotateCcwIcon />
                              {t("tasks.detail.retryRun")}
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {(runMutation.isError || cancelMutation.isError) && (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {(runMutation.error ?? cancelMutation.error)?.message}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("tasks.detail.infoTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-4 text-sm">
              <Detail
                label={t("tasks.columns.state")}
                value={<StatusBadge tone="neutral">{t(`tasks.states.${item.state}`)}</StatusBadge>}
              />
              <Detail
                label={t("tasks.columns.priority")}
                value={t(`tasks.priorities.${item.priority}`)}
              />
              <Detail label={t("tasks.columns.project")} value={projectName ?? "—"} />
              <Detail label={t("tasks.detail.assignee")} value={agentName ?? "—"} />
              <Detail
                label={t("tasks.columns.due")}
                value={timestamp(item.due_at, i18n.language)}
              />
              <Detail
                label={t("tasks.detail.created")}
                value={timestamp(item.created_at, i18n.language)}
              />
              <Detail
                label={t("tasks.detail.updated")}
                value={timestamp(item.updated_at, i18n.language)}
              />
              <Detail
                label={t("tasks.detail.taskId")}
                value={<code className="break-all text-xs">{item.id}</code>}
              />
              <Detail label={t("tasks.detail.version")} value={String(item.version)} />
            </dl>
          </CardContent>
        </Card>
      </div>
      <Dialog open={runDialogOpen} onOpenChange={setRunDialogOpen}>
        <DialogContent>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!runtimeId || !workspace.trim()) return;
              runMutation.mutate({ runtime_id: runtimeId, workspace: workspace.trim() });
            }}
          >
            <DialogHeader>
              <DialogTitle>{t("tasks.detail.startDialog.title")}</DialogTitle>
              <DialogDescription>{t("tasks.detail.startDialog.description")}</DialogDescription>
            </DialogHeader>
            <div className="my-5 space-y-4">
              <label className="block space-y-1.5 text-sm">
                <span>{t("tasks.detail.startDialog.runtime")}</span>
                <select
                  aria-label={t("tasks.detail.startDialog.runtime")}
                  value={runtimeId}
                  onChange={(event) => setRuntimeId(event.target.value)}
                  className="h-9 w-full rounded-lg border bg-background px-3 text-foreground"
                >
                  {availableHosts.map((host) => (
                    <option key={host.host_id} value={host.host_id}>
                      {host.name}
                    </option>
                  ))}
                </select>
                {!hosts.isLoading && availableHosts.length === 0 && (
                  <span className="block text-xs text-destructive">
                    {t("tasks.detail.startDialog.noRuntime")}
                  </span>
                )}
              </label>
              <label className="block space-y-1.5 text-sm">
                <span>{t("tasks.detail.startDialog.workspace")}</span>
                <Input
                  aria-label={t("tasks.detail.startDialog.workspace")}
                  value={workspace}
                  onChange={(event) => setWorkspace(event.target.value)}
                  placeholder={t("tasks.detail.startDialog.workspacePlaceholder")}
                />
              </label>
              {runMutation.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {runMutation.error.message}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="submit"
                loading={runMutation.isPending}
                disabled={!runtimeId || !workspace.trim()}
              >
                <PlayIcon />
                {t("tasks.detail.startDialog.submit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </PageScroll>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1">{value}</dd>
    </div>
  );
}
