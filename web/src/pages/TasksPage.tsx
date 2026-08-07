import { useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  DndContext,
  type DragEndEvent,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BotIcon,
  GripVerticalIcon,
  LayoutGridIcon,
  ListIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
  UserRoundIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { PageScroll } from "@/components/PageScroll";
import { iconForAgent } from "@/components/AgentCard";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  EntityTable,
  StatusBadge,
} from "@/components/collection";
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
import { Textarea } from "@/components/ui/textarea";
import { useAvailableAgents, type AvailableAgent } from "@/hooks/useAvailableAgents";
import { useProjects } from "@/hooks/useConversations";
import { cn } from "@/lib/utils";
import { TASK_STATES, type TaskState } from "@/lib/workLifecycle";
import { userColor, userColorTint } from "@/lib/userBadge";
import {
  WORK_ITEM_PRIORITIES,
  createWorkItem,
  listWorkItems,
  updateWorkItem,
  type WorkItem,
  type WorkItemPriority,
} from "@/lib/workItemsApi";
import { Link, useSearchParams } from "@/lib/routing";

const WORK_ITEMS_KEY = ["work-items"] as const;

type TaskView = "board" | "list";

const TASK_STATE_VISUALS: Record<
  TaskState,
  { accent: string; surface: number; badge: "neutral" | "info" | "success" | "warning" | "danger" }
> = {
  backlog: { accent: "var(--chart-5)", surface: 5, badge: "neutral" },
  todo: { accent: "var(--muted-foreground)", surface: 4, badge: "neutral" },
  in_progress: { accent: "var(--chart-4)", surface: 9, badge: "warning" },
  review: { accent: "var(--chart-3)", surface: 8, badge: "success" },
  done: { accent: "var(--chart-1)", surface: 8, badge: "info" },
  blocked: { accent: "var(--brand-accent)", surface: 8, badge: "warning" },
  failed: { accent: "var(--destructive)", surface: 9, badge: "danger" },
  cancelled: { accent: "var(--chart-5)", surface: 3, badge: "neutral" },
};

function setParam(
  params: URLSearchParams,
  setParams: ReturnType<typeof useSearchParams>[1],
  key: string,
  value: string,
  defaultValue = "",
) {
  const next = new URLSearchParams(params);
  if (!value || value === defaultValue) next.delete(key);
  else next.set(key, value);
  setParams(next, { replace: true });
}

function timestampLabel(value: number | null, language: string): string {
  if (value == null) return "—";
  return new Intl.DateTimeFormat(language).format(new Date(value * 1000));
}

export function TasksPage() {
  const { t, i18n } = useTranslation("management");
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  const projects = useProjects();
  const agents = useAvailableAgents();
  const tasks = useQuery({ queryKey: WORK_ITEMS_KEY, queryFn: listWorkItems });

  const view: TaskView = params.get("view") === "list" ? "list" : "board";
  const query = params.get("q") ?? "";
  const stateFilter = params.get("state") ?? "all";
  const priorityFilter = params.get("priority") ?? "all";
  const projectFilter = params.get("project") ?? "all";
  const agentFilter = params.get("agent") ?? "all";

  const updateMutation = useMutation({
    mutationFn: ({ item, state }: { item: WorkItem; state: TaskState }) =>
      updateWorkItem(item.id, { state, expected_version: item.version }),
    onMutate: async ({ item, state }) => {
      await queryClient.cancelQueries({ queryKey: WORK_ITEMS_KEY });
      const previous = queryClient.getQueryData<WorkItem[]>(WORK_ITEMS_KEY);
      queryClient.setQueryData<WorkItem[]>(WORK_ITEMS_KEY, (current) =>
        current?.map((candidate) =>
          candidate.id === item.id
            ? { ...candidate, state, version: candidate.version + 1 }
            : candidate,
        ),
      );
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(WORK_ITEMS_KEY, context.previous);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData<WorkItem[]>(WORK_ITEMS_KEY, (current) =>
        current?.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
      );
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: WORK_ITEMS_KEY, exact: true }),
  });

  const rows = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(i18n.language);
    return (tasks.data ?? []).filter((item) => {
      if (stateFilter !== "all" && item.state !== stateFilter) return false;
      if (priorityFilter !== "all" && item.priority !== priorityFilter) return false;
      if (projectFilter !== "all" && item.project_id !== projectFilter) return false;
      if (agentFilter !== "all" && item.assignee_agent_id !== agentFilter) return false;
      return (
        !normalized ||
        item.title.toLocaleLowerCase(i18n.language).includes(normalized) ||
        item.description?.toLocaleLowerCase(i18n.language).includes(normalized)
      );
    });
  }, [agentFilter, i18n.language, priorityFilter, projectFilter, query, stateFilter, tasks.data]);

  const projectNames = new Map(
    (projects.data ?? [])
      .filter((project) => project.id)
      .map((project) => [project.id as string, project.name]),
  );
  const agentById = new Map((agents.data ?? []).map((agent) => [agent.id, agent]));
  const agentNames = new Map(
    [...agentById].map(([id, agent]) => [id, agent.display_name || agent.name]),
  );

  function moveInto(id: string, state: TaskState) {
    const item = tasks.data?.find((candidate) => candidate.id === id);
    if (item && item.state !== state && !updateMutation.isPending) {
      updateMutation.mutate({ item, state });
    }
  }

  const loading = tasks.isLoading || projects.isLoading || agents.isLoading;
  const failed = tasks.isError || projects.isError || agents.isError;

  return (
    <PageScroll contentClassName="px-6" maxWidthClassName="max-w-none" data-testid="tasks-page">
      <CollectionPageHeader
        title={t("tasks.title")}
        description={t("tasks.description")}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <PlusIcon className="size-4" />
            {t("tasks.newTask")}
          </Button>
        }
      />

      <CollectionToolbar className="mt-6">
        <div className="relative min-w-52 flex-1 sm:max-w-xs">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label={t("common.search")}
            value={query}
            onChange={(event) => setParam(params, setParams, "q", event.target.value)}
            placeholder={t("tasks.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <TaskFilter
          label={t("tasks.filters.state")}
          value={stateFilter}
          onChange={(value) => setParam(params, setParams, "state", value, "all")}
          options={TASK_STATES.map((state) => ({
            value: state,
            label: t(`tasks.states.${state}`),
          }))}
          allLabel={t("common.all")}
        />
        <TaskFilter
          label={t("tasks.filters.priority")}
          value={priorityFilter}
          onChange={(value) => setParam(params, setParams, "priority", value, "all")}
          options={WORK_ITEM_PRIORITIES.map((priority) => ({
            value: priority,
            label: t(`tasks.priorities.${priority}`),
          }))}
          allLabel={t("common.all")}
        />
        <TaskFilter
          label={t("tasks.filters.project")}
          value={projectFilter}
          onChange={(value) => setParam(params, setParams, "project", value, "all")}
          options={[...projectNames].map(([value, label]) => ({ value, label }))}
          allLabel={t("common.all")}
        />
        <TaskFilter
          label={t("tasks.filters.agent")}
          value={agentFilter}
          onChange={(value) => setParam(params, setParams, "agent", value, "all")}
          options={[...agentNames].map(([value, label]) => ({ value, label }))}
          allLabel={t("common.all")}
        />
        <div
          className="flex rounded-lg border p-0.5"
          role="group"
          aria-label={t("tasks.viewLabel")}
        >
          <Button
            size="icon-sm"
            variant={view === "board" ? "secondary" : "ghost"}
            aria-label={t("tasks.views.board")}
            onClick={() => setParam(params, setParams, "view", "board", "board")}
          >
            <LayoutGridIcon className="size-4" />
          </Button>
          <Button
            size="icon-sm"
            variant={view === "list" ? "secondary" : "ghost"}
            aria-label={t("tasks.views.list")}
            onClick={() => setParam(params, setParams, "view", "list", "board")}
          >
            <ListIcon className="size-4" />
          </Button>
        </div>
      </CollectionToolbar>

      {updateMutation.isError && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {t("tasks.updateError", { message: updateMutation.error.message })}
        </p>
      )}

      <div className="mt-4">
        {loading ? (
          <CollectionState state="loading" title={t("tasks.loading")} />
        ) : failed ? (
          <CollectionState
            state="error"
            title={t("tasks.error")}
            action={
              <button
                type="button"
                className="text-sm font-medium text-primary"
                onClick={() =>
                  void Promise.all([tasks.refetch(), projects.refetch(), agents.refetch()])
                }
              >
                {t("common.retry")}
              </button>
            }
          />
        ) : (tasks.data?.length ?? 0) === 0 ? (
          <CollectionState
            state="empty"
            title={t("tasks.empty")}
            description={t("tasks.emptyDescription")}
            action={<Button onClick={() => setCreateOpen(true)}>{t("tasks.newTask")}</Button>}
          />
        ) : rows.length === 0 ? (
          <CollectionState state="empty" title={t("tasks.noMatches")} />
        ) : view === "board" ? (
          <TaskBoard
            rows={rows}
            projectNames={projectNames}
            agents={agentById}
            moving={updateMutation.isPending}
            onMove={moveInto}
            t={t}
          />
        ) : (
          <TaskList
            rows={rows}
            projectNames={projectNames}
            agents={agentById}
            language={i18n.language}
            t={t}
          />
        )}
      </div>

      <CreateTaskDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        projects={projectNames}
        agents={agentNames}
      />
    </PageScroll>
  );
}

function TaskFilter({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-lg border bg-background px-2 text-sm text-foreground"
      >
        <option value="all">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

type Translation = ReturnType<typeof useTranslation<"management">>["t"];

function TaskBoard({
  rows,
  projectNames,
  agents,
  moving,
  onMove,
  t,
}: {
  rows: WorkItem[];
  projectNames: Map<string, string>;
  agents: Map<string, AvailableAgent>;
  moving: boolean;
  onMove: (id: string, state: TaskState) => void;
  t: Translation;
}) {
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const state = String(event.over?.id ?? "");
    if (TASK_STATES.includes(state as TaskState)) {
      onMove(String(event.active.id), state as TaskState);
    }
  }

  return (
    <div className="overflow-x-auto pb-4" data-testid="task-board">
      <DndContext sensors={sensors} collisionDetection={pointerWithin} onDragEnd={handleDragEnd}>
        <div className="flex min-w-max gap-3">
          {TASK_STATES.map((state) => (
            <TaskBoardColumn
              key={state}
              state={state}
              rows={rows.filter((item) => item.state === state)}
              projectNames={projectNames}
              agents={agents}
              moving={moving}
              t={t}
            />
          ))}
        </div>
      </DndContext>
    </div>
  );
}

function TaskBoardColumn({
  state,
  rows,
  projectNames,
  agents,
  moving,
  t,
}: {
  state: TaskState;
  rows: WorkItem[];
  projectNames: Map<string, string>;
  agents: Map<string, AvailableAgent>;
  moving: boolean;
  t: Translation;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: state, disabled: moving });
  const visual = TASK_STATE_VISUALS[state];

  return (
    <section
      ref={setNodeRef}
      aria-label={t(`tasks.states.${state}`)}
      style={{
        backgroundColor: `color-mix(in oklab, ${visual.accent} ${visual.surface}%, var(--card))`,
        borderColor: `color-mix(in oklab, ${visual.accent} 24%, var(--border))`,
      }}
      className={cn(
        "min-h-64 w-[264px] shrink-0 rounded-xl border p-2 transition-[background-color,box-shadow]",
        isOver && "ring-2 ring-offset-1 ring-offset-background",
      )}
    >
      <header className="mb-2 flex items-center justify-between px-1 py-1">
        <h2 className="flex items-center gap-2 text-sm font-medium">
          <span
            aria-hidden="true"
            className="size-2 rounded-full shadow-[0_0_0_3px_color-mix(in_oklab,currentColor_12%,transparent)]"
            style={{ backgroundColor: visual.accent, color: visual.accent }}
          />
          {t(`tasks.states.${state}`)}
        </h2>
        <span className="text-xs text-muted-foreground tabular-nums">{rows.length}</span>
      </header>
      <div className="space-y-2">
        {rows.map((item) => (
          <TaskBoardCard
            key={item.id}
            item={item}
            projectNames={projectNames}
            agents={agents}
            moving={moving}
            t={t}
          />
        ))}
      </div>
    </section>
  );
}

function TaskBoardCard({
  item,
  projectNames,
  agents,
  moving,
  t,
}: {
  item: WorkItem;
  projectNames: Map<string, string>;
  agents: Map<string, AvailableAgent>;
  moving: boolean;
  t: Translation;
}) {
  const { attributes, isDragging, listeners, setNodeRef, transform } = useDraggable({
    id: item.id,
    disabled: moving,
  });
  const style: CSSProperties | undefined = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;
  const assignee = item.assignee_agent_id ? agents.get(item.assignee_agent_id) : undefined;
  const creatorAgent = item.created_by_agent_id ? agents.get(item.created_by_agent_id) : undefined;
  const AssigneeIcon = assignee ? iconForAgent(assignee) : BotIcon;
  const projectName = item.project_id ? projectNames.get(item.project_id) : undefined;
  const creatorLabel =
    item.creator_kind === "agent"
      ? t("tasks.createdBy.agent", {
          name: creatorAgent?.display_name || creatorAgent?.name || t("tasks.createdBy.ai"),
        })
      : item.creator_kind === "automation"
        ? t("tasks.createdBy.automation")
        : t("tasks.createdBy.user");

  return (
    <article
      ref={setNodeRef}
      style={style}
      className={cn(
        "relative rounded-lg border bg-card p-3 pr-9 shadow-xs",
        isDragging && "z-10 opacity-60 shadow-md",
      )}
    >
      <button
        type="button"
        aria-label={t("tasks.dragHandle", { title: item.title })}
        className="absolute top-2 right-2 cursor-grab touch-none rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVerticalIcon className="size-4" />
      </button>
      <Link to={`/tasks/${encodeURIComponent(item.id)}`} className="font-medium hover:underline">
        {item.title}
      </Link>
      {item.description && (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <StatusBadge
          tone={
            item.priority === "urgent" ? "danger" : item.priority === "high" ? "warning" : "neutral"
          }
        >
          {t(`tasks.priorities.${item.priority}`)}
        </StatusBadge>
        {item.project_id && projectName && (
          <span
            className="inline-flex max-w-full items-center gap-1.5 truncate rounded-full px-2 py-0.5 text-xs"
            style={{
              color: userColor(item.project_id),
              backgroundColor: userColorTint(item.project_id),
            }}
          >
            <span className="size-1.5 shrink-0 rounded-full bg-current" />
            {projectName}
          </span>
        )}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border/60 pt-2.5">
        {assignee ? (
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="flex size-6 shrink-0 items-center justify-center rounded-full ring-1 ring-inset"
              style={{
                color: userColor(assignee.id),
                backgroundColor: userColorTint(assignee.id),
              }}
            >
              <AssigneeIcon className="size-3.5" />
            </span>
            <span className="truncate">{assignee.display_name || assignee.name}</span>
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="flex size-6 items-center justify-center rounded-full bg-muted">
              <BotIcon className="size-3.5" />
            </span>
            {t("tasks.createdBy.unassigned")}
          </span>
        )}
        <span className="flex max-w-28 shrink-0 items-center gap-1 truncate text-[11px] text-muted-foreground">
          {item.creator_kind === "agent" || item.creator_kind === "automation" ? (
            <SparklesIcon className="size-3" />
          ) : (
            <UserRoundIcon className="size-3" />
          )}
          {creatorLabel}
        </span>
      </div>
    </article>
  );
}

function TaskList({
  rows,
  projectNames,
  agents,
  language,
  t,
}: {
  rows: WorkItem[];
  projectNames: Map<string, string>;
  agents: Map<string, AvailableAgent>;
  language: string;
  t: Translation;
}) {
  return (
    <EntityTable
      caption={t("tasks.tableCaption")}
      columns={[
        { key: "task", label: t("tasks.columns.task") },
        { key: "state", label: t("tasks.columns.state") },
        { key: "priority", label: t("tasks.columns.priority") },
        { key: "project", label: t("tasks.columns.project") },
        { key: "due", label: t("tasks.columns.due") },
      ]}
    >
      {rows.map((item) => (
        <tr key={item.id} className="hover:bg-muted/30">
          <td className="px-3 py-3">
            <Link
              to={`/tasks/${encodeURIComponent(item.id)}`}
              className="font-medium hover:underline"
            >
              {item.title}
            </Link>
            {item.description && (
              <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{item.description}</p>
            )}
          </td>
          <td className="px-3 py-3">
            <StatusBadge tone={TASK_STATE_VISUALS[item.state].badge}>
              {t(`tasks.states.${item.state}`)}
            </StatusBadge>
          </td>
          <td className="px-3 py-3">{t(`tasks.priorities.${item.priority}`)}</td>
          <td className="px-3 py-3 text-muted-foreground">
            {item.project_id ? (projectNames.get(item.project_id) ?? "—") : "—"}
            {item.assignee_agent_id && agents.has(item.assignee_agent_id) ? (
              <p className="mt-1 text-xs text-muted-foreground">
                {agents.get(item.assignee_agent_id)?.display_name}
              </p>
            ) : null}
          </td>
          <td className="px-3 py-3 text-muted-foreground">
            {timestampLabel(item.due_at, language)}
          </td>
        </tr>
      ))}
    </EntityTable>
  );
}

function CreateTaskDialog({
  open,
  onOpenChange,
  projects,
  agents,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: Map<string, string>;
  agents: Map<string, string>;
}) {
  const { t } = useTranslation("management");
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<WorkItemPriority>("medium");
  const [projectId, setProjectId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [dueDate, setDueDate] = useState("");
  const mutation = useMutation({
    mutationFn: createWorkItem,
    onSuccess: (created) => {
      queryClient.setQueryData<WorkItem[]>(WORK_ITEMS_KEY, (current) => [
        created,
        ...(current ?? []),
      ]);
      setTitle("");
      setDescription("");
      setPriority("medium");
      setProjectId("");
      setAgentId("");
      setDueDate("");
      onOpenChange(false);
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: WORK_ITEMS_KEY, exact: true }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) return;
    mutation.mutate({
      title: trimmed,
      ...(description.trim() ? { description: description.trim() } : {}),
      priority,
      ...(projectId ? { project_id: projectId } : {}),
      ...(agentId ? { assignee_agent_id: agentId } : {}),
      ...(dueDate ? { due_at: Math.floor(new Date(`${dueDate}T00:00:00`).getTime() / 1000) } : {}),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="contents">
          <DialogHeader>
            <DialogTitle>{t("tasks.create.title")}</DialogTitle>
            <DialogDescription>{t("tasks.create.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="work-item-title" className="text-sm font-medium">
                {t("tasks.create.fields.title")}
              </label>
              <Input
                id="work-item-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                autoFocus
                maxLength={256}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="work-item-description" className="text-sm font-medium">
                {t("tasks.create.fields.description")}
              </label>
              <Textarea
                id="work-item-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={4}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <CreateSelect
                label={t("tasks.create.fields.priority")}
                value={priority}
                onChange={(value) => setPriority(value as WorkItemPriority)}
                options={WORK_ITEM_PRIORITIES.map((value) => ({
                  value,
                  label: t(`tasks.priorities.${value}`),
                }))}
              />
              <CreateSelect
                label={t("tasks.create.fields.project")}
                value={projectId}
                onChange={setProjectId}
                options={[...projects].map(([value, label]) => ({ value, label }))}
                emptyLabel={t("tasks.create.noProject")}
              />
              <CreateSelect
                label={t("tasks.create.fields.agent")}
                value={agentId}
                onChange={setAgentId}
                options={[...agents].map(([value, label]) => ({ value, label }))}
                emptyLabel={t("tasks.create.unassigned")}
              />
              <div className="space-y-1.5">
                <label htmlFor="work-item-due" className="text-sm font-medium">
                  {t("tasks.create.fields.due")}
                </label>
                <Input
                  id="work-item-due"
                  type="date"
                  value={dueDate}
                  onInput={(event) => setDueDate(event.currentTarget.value)}
                />
              </div>
            </div>
            {mutation.isError && (
              <p role="alert" className="text-sm text-destructive">
                {mutation.error.message}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!title.trim() || mutation.isPending}>
              {mutation.isPending ? t("tasks.create.creating") : t("tasks.create.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CreateSelect({
  label,
  value,
  onChange,
  options,
  emptyLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  emptyLabel?: string;
}) {
  return (
    <label className="space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 w-full rounded-lg border bg-background px-2 text-sm"
      >
        {emptyLabel && <option value="">{emptyLabel}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
