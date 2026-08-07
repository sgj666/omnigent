// One row in the Tasks list, rendered as a CARD (border + subtle background +
// rounded corners + internal padding; the list stacks these with a gap). Layout:
// bold task title on line 1 (+ a small "Paused" pill when paused), a single
// muted subline on line 2 with the human-readable schedule summary ("Weekdays
// at 8:00 AM") followed by the next-run time ("· Next run in 3 hours") when
// armed.
//
// The next-run time is derived from the scheduler's authoritative `nextRunAt`
// (an ISO string the server computes): we only FORMAT the delta from that
// instant (a full-words "in N hours / days" label), never recompute WHICH
// instant is next on the client — so the "no client countdown" rule (a
// client-recomputed instant can't match the server anchor for INTERVAL>1 rules)
// is not violated. Paused rows are NOT dimmed — the title stays fully legible
// and the pill is the sole paused signal. A hover-revealed ellipsis (⋯) action
// menu (Run now / Pause / Resume / Edit / Delete) sits on the right.

import { useMemo, useState } from "react";
import {
  MoreHorizontalIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge, type StatusTone } from "@/components/collection";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { describeSchedule, formatNextRunAt, localizeScheduleSummary } from "@/lib/scheduleText";
import type { ScheduledTask } from "@/lib/scheduledTasksApi";
import { Link } from "@/lib/routing";

function runStatusTone(status: ScheduledTask["lastRunStatus"]): StatusTone {
  if (status === "succeeded") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "scheduled") return "info";
  if (status === "skipped" || status === "incomplete") return "warning";
  return "neutral";
}

export function ScheduledTaskRow({
  task,
  now,
  onEdit,
  onPauseToggle,
  onRunNow,
  onDelete,
  busy,
}: {
  task: ScheduledTask;
  // The current wall-clock time, supplied by the parent's shared `useNow` ticker
  // so the relative next-run label ("in 3 hours") re-renders and stays fresh as
  // time passes. Passed in (not read here) to keep the row a pure function of
  // props — one ticker for the whole list, and deterministic in tests.
  now: Date;
  onEdit: (task: ScheduledTask) => void;
  onPauseToggle: (task: ScheduledTask) => void;
  onRunNow: (task: ScheduledTask) => void;
  onDelete: (task: ScheduledTask) => void;
  busy: boolean;
}) {
  const { t, i18n } = useTranslation("tasks");
  const [menuOpen, setMenuOpen] = useState(false);
  const paused = task.state === "paused";
  // Subtitle: the schedule summary, plus the SERVER's next-run time when armed
  // (active tasks only — a paused task has null nextRunAt). We only format the
  // delta from the server value against the ticking `now`; we never recompute
  // WHICH instant is next on the client.
  const scheduleSummary = useMemo(
    () =>
      localizeScheduleSummary(describeSchedule(task.rrule), i18n.resolvedLanguage ?? i18n.language),
    [task.rrule, i18n.language, i18n.resolvedLanguage],
  );
  const nextRun = useMemo(
    () =>
      localizeScheduleSummary(
        formatNextRunAt(task.nextRunAt, now) ?? "",
        i18n.resolvedLanguage ?? i18n.language,
      ),
    [task.nextRunAt, now, i18n.language, i18n.resolvedLanguage],
  );
  const lastRunDate = useMemo(() => {
    if (task.lastRunAt == null) return null;
    return new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language).format(
      new Date(task.lastRunAt * 1000),
    );
  }, [task.lastRunAt, i18n.language, i18n.resolvedLanguage]);
  const hasLastRunIssue =
    task.lastRunStatus === "failed" ||
    task.lastRunStatus === "skipped" ||
    task.lastRunStatus === "incomplete";
  const lastRunReason = hasLastRunIssue
    ? t(`runError.${task.lastRunErrorCode ?? task.lastRunStatus}`, {
        defaultValue: t("runError.unknown"),
      })
    : null;

  return (
    <div
      data-testid="scheduled-task-row"
      data-state={task.state}
      className={cn(
        // Card chrome — matching the app's card vocabulary (`rounded-xl border
        // border-border bg-card`, see InboxPage rows / the Card component): a
        // visible border, subtle card background, rounded corners, and internal
        // padding. The list container (AutomationsPage) stacks these with a `gap` so
        // there is vertical spacing between cards. `group relative` lets the
        // absolutely-positioned ⋯ trigger hover-reveal; `pr-12` keeps the text
        // clear of the inset button, whose `right-3` matches the card's `px-4`
        // inset so the two edges are symmetric. A subtle `hover:bg-muted/40`
        // keeps the full-card hover affordance. Paused rows are NOT dimmed — the
        // title must stay legible (AA); the "Paused" pill is the sole signal.
        "group relative flex items-center gap-3 rounded-xl border border-border bg-card py-3 pr-12 pl-4 transition-colors hover:bg-muted/40",
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[15px] font-semibold">{task.name}</span>
          {paused && (
            <span
              data-testid="task-paused-pill"
              className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
            >
              {t("paused")}
            </span>
          )}
        </span>
        <span
          className="truncate text-[13px] text-muted-foreground/80"
          data-testid="task-schedule-line"
        >
          {scheduleSummary}
          {nextRun && (
            <>
              {" · "}
              <span data-testid="task-next-run">{t("nextRun", { value: nextRun })}</span>
            </>
          )}
        </span>
        <span className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="max-w-48 truncate">{t("agentTarget", { agent: task.agentId })}</span>
          <span aria-hidden>·</span>
          <span>{lastRunDate ? t("lastRunAt", { date: lastRunDate }) : t("neverRun")}</span>
          {task.lastRunStatus ? (
            task.lastRunConversationId ? (
              <Link
                to={`/c/${task.lastRunConversationId}`}
                aria-label={t("openLastRun")}
                className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <StatusBadge tone={runStatusTone(task.lastRunStatus)}>
                  {t(`runStatus.${task.lastRunStatus}`)}
                </StatusBadge>
              </Link>
            ) : (
              <StatusBadge tone={runStatusTone(task.lastRunStatus)}>
                {t(`runStatus.${task.lastRunStatus}`)}
              </StatusBadge>
            )
          ) : null}
        </span>
        {lastRunReason ? (
          <p
            className={cn(
              "mt-1 text-[11px]",
              task.lastRunStatus === "failed" ? "text-destructive" : "text-warning-foreground",
            )}
            data-testid="task-last-run-issue"
          >
            {t("lastRunIssue")}: {lastRunReason}
            {task.lastRunErrorCode ? (
              <code className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                {task.lastRunErrorCode}
              </code>
            ) : null}
          </p>
        ) : null}
      </div>

      {/* Hover-revealed ellipsis menu, mirroring the sidebar conversation-row
          action button: absolute-positioned on the right, hidden until the row
          is hovered / focused, and kept surfaced while the menu is open via
          `aria-expanded`. */}
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t("actionsFor", { name: task.name })}
            data-testid="task-row-menu"
            disabled={busy}
            className={cn(
              "-translate-y-1/2 absolute top-1/2 right-3 transition-opacity",
              "md:opacity-0 md:group-hover:opacity-100 md:group-has-[:focus-visible]:opacity-100",
              "md:aria-expanded:opacity-100",
            )}
          >
            <MoreHorizontalIcon className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => onRunNow(task)} data-testid="task-run-now">
            <ZapIcon className="size-4" />
            {t("runNow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onEdit(task)} data-testid="task-edit">
            <PencilIcon className="size-4" />
            {t("edit")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onPauseToggle(task)} data-testid="task-pause-toggle">
            {paused ? (
              <>
                <PlayIcon className="size-4" />
                {t("resume")}
              </>
            ) : (
              <>
                <PauseIcon className="size-4" />
                {t("pause")}
              </>
            )}
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => onDelete(task)}
            data-testid="task-delete"
          >
            <Trash2Icon className="size-4" />
            {t("delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
