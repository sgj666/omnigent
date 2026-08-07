import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { SearchIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageScroll } from "@/components/PageScroll";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  EntityTable,
  SegmentedFilter,
} from "@/components/collection";
import { Input } from "@/components/ui/input";
import { isPermissionDenied } from "@/lib/httpErrors";
import { Link, useSearchParams } from "@/lib/routing";
import { getUsageReport } from "@/lib/usageApi";
import { cn } from "@/lib/utils";

type UsagePeriod = "today" | "7d" | "30d" | "all";
type BreakdownDimension = "projects" | "agents" | "runtimes" | "skills";

function formatCurrency(value: number, language: string): string {
  return new Intl.NumberFormat(language, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
    maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
  }).format(value);
}

function formatNumber(value: number, language: string): string {
  return new Intl.NumberFormat(language, {
    notation: value >= 10_000 ? "compact" : "standard",
  }).format(value);
}

function formatDate(value: number, language: string): string {
  return new Intl.DateTimeFormat(language).format(new Date(value * 1000));
}

function formatDay(value: string, language: string): string {
  return new Intl.DateTimeFormat(language, { month: "short", day: "numeric" }).format(
    new Date(`${value}T00:00:00Z`),
  );
}

function formatPercent(value: number | null, language: string): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 }).format(
    value,
  );
}

function formatDuration(
  value: number | null,
  language: string,
  t: TFunction<"management">,
): string {
  if (value === null) return "—";
  if (value < 60)
    return t("usage.durationSeconds", { value: formatNumber(Math.round(value), language) });
  return t("usage.durationMinutes", { value: formatNumber(Math.round(value / 6) / 10, language) });
}

function DailyCostTrend({
  data,
  language,
  title,
  description,
  emptyLabel,
  totalLabel,
}: {
  data: { day_utc: string; cost_usd: number }[];
  language: string;
  title: string;
  description: string;
  emptyLabel: string;
  totalLabel: string;
}) {
  const width = Math.max(760, data.length * 22);
  const height = 220;
  const insetX = 24;
  const insetY = 24;
  const baseline = height - insetY;
  const maxCost = Math.max(...data.map((point) => point.cost_usd), 0);
  const chartMax = maxCost > 0 ? maxCost : 1;
  const xAt = (index: number) =>
    data.length <= 1 ? width / 2 : insetX + (index / (data.length - 1)) * (width - insetX * 2);
  const yAt = (value: number) => baseline - (value / chartMax) * (height - insetY * 2);
  const line = data.map((point, index) => `${xAt(index)},${yAt(point.cost_usd)}`).join(" ");
  const area =
    data.length > 0
      ? `M ${xAt(0)} ${baseline} ${data
          .map((point, index) => `L ${xAt(index)} ${yAt(point.cost_usd)}`)
          .join(" ")} L ${xAt(data.length - 1)} ${baseline} Z`
      : "";
  const total = data.reduce((sum, point) => sum + point.cost_usd, 0);

  return (
    <section className="mt-5 overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">{totalLabel}</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {formatCurrency(total, language)}
          </p>
        </div>
      </div>
      {data.length === 0 ? (
        <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">
          {emptyLabel}
        </div>
      ) : (
        <div className="overflow-x-auto px-3 pt-3 pb-2">
          <svg
            role="img"
            aria-label={`${title}: ${formatCurrency(total, language)}`}
            viewBox={`0 0 ${width} ${height}`}
            className="h-56"
            style={{ minWidth: width, width: "100%" }}
          >
            {[0.25, 0.5, 0.75, 1].map((ratio) => (
              <line
                key={ratio}
                x1={insetX}
                x2={width - insetX}
                y1={baseline - ratio * (height - insetY * 2)}
                y2={baseline - ratio * (height - insetY * 2)}
                stroke="var(--border)"
                strokeWidth="1"
                strokeDasharray="3 5"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            <path d={area} fill="color-mix(in oklab, var(--chart-2) 13%, transparent)" />
            <polyline
              points={line}
              fill="none"
              stroke="var(--chart-2)"
              strokeWidth="2.5"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
            {data.map((point, index) => (
              <circle
                key={point.day_utc}
                cx={xAt(index)}
                cy={yAt(point.cost_usd)}
                r={data.length <= 31 ? 3 : 2}
                fill="var(--card)"
                stroke="var(--chart-2)"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              >
                <title>{`${formatDay(point.day_utc, language)} · ${formatCurrency(point.cost_usd, language)}`}</title>
              </circle>
            ))}
          </svg>
          <div
            className="flex justify-between px-3 text-[11px] text-muted-foreground"
            style={{ minWidth: width }}
          >
            <span>{formatDay(data[0]!.day_utc, language)}</span>
            {data.length > 2 ? (
              <span>{formatDay(data[Math.floor(data.length / 2)]!.day_utc, language)}</span>
            ) : null}
            <span>{formatDay(data[data.length - 1]!.day_utc, language)}</span>
          </div>
        </div>
      )}
    </section>
  );
}

export function UsagePage() {
  const { t, i18n } = useTranslation("management");
  const { t: commonT } = useTranslation("common");
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const rawPeriod = params.get("range");
  const period: UsagePeriod =
    rawPeriod === "today" || rawPeriod === "7d" || rawPeriod === "all" ? rawPeriod : "30d";
  const rawDimension = params.get("by");
  const dimension: BreakdownDimension =
    rawDimension === "agents" || rawDimension === "runtimes" || rawDimension === "skills"
      ? rawDimension
      : "projects";
  const projectId = params.get("project") || undefined;
  const agentId = params.get("agent") || undefined;
  const report = useQuery({
    queryKey: ["usage", period, projectId ?? "", agentId ?? ""],
    queryFn: ({ signal }) => getUsageReport({ range: period, projectId, agentId }, signal),
  });

  function updateParam(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const sessions = useMemo(() => report.data?.sessions ?? [], [report.data?.sessions]);
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(i18n.language);
    if (!query) return sessions;
    return sessions.filter((session) =>
      [session.title ?? "", session.id, ...Object.keys(session.models)].some((value) =>
        value.toLocaleLowerCase(i18n.language).includes(query),
      ),
    );
  }, [i18n.language, search, sessions]);

  const periodCosts: Record<UsagePeriod, number> = {
    today: report.data?.cost_today ?? 0,
    "7d": report.data?.cost_last_7d ?? 0,
    "30d": report.data?.cost_last_30d ?? 0,
    all: report.data?.total_cost_usd ?? 0,
  };
  const totalTokens = sessions.reduce((sum, session) => sum + session.total_tokens, 0);
  const operations = report.data?.operations;
  const breakdownRows = report.data?.breakdowns[dimension] ?? [];
  const taskRuns = report.data?.task_runs ?? [];

  function breakdownTarget(row: { id: string }): string | null {
    if (dimension === "projects") return `/projects/${row.id}`;
    if (dimension === "agents") return `/multi-agents/${row.id}`;
    if (dimension === "runtimes") return `/runtime/${row.id}`;
    return null;
  }

  return (
    <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl" data-testid="usage-page">
      <CollectionPageHeader title={t("usage.title")} description={t("usage.description")} />
      {report.isLoading ? (
        <CollectionState className="mt-6" state="loading" title={t("usage.loading")} />
      ) : report.isError ? (
        <CollectionState
          className="mt-6"
          state="error"
          title={
            isPermissionDenied(report.error)
              ? commonT("collection.permissionDenied")
              : t("usage.error")
          }
          description={
            isPermissionDenied(report.error)
              ? commonT("collection.permissionDeniedDescription")
              : undefined
          }
          action={
            <button
              type="button"
              className="text-sm font-medium text-primary"
              onClick={() => void report.refetch()}
            >
              {t("common.retry")}
            </button>
          }
        />
      ) : (
        <>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t("usage.periodLabel")}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">{t("usage.rangeDescription")}</p>
            </div>
            <SegmentedFilter<UsagePeriod>
              label={t("usage.periodLabel")}
              value={period}
              onValueChange={(value) => updateParam("range", value, "30d")}
              options={[
                { value: "today", label: t("usage.periods.today") },
                { value: "7d", label: t("usage.periods.7d") },
                { value: "30d", label: t("usage.periods.30d") },
                { value: "all", label: t("usage.periods.all") },
              ]}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-3 rounded-xl border border-border bg-muted/20 p-3">
            <label className="flex min-w-52 flex-1 flex-col gap-1 text-xs text-muted-foreground">
              {t("usage.projectFilter")}
              <select
                aria-label={t("usage.projectFilter")}
                value={projectId ?? ""}
                onChange={(event) => updateParam("project", event.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
              >
                <option value="">{t("usage.allProjects")}</option>
                {(report.data?.filter_options.projects ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-52 flex-1 flex-col gap-1 text-xs text-muted-foreground">
              {t("usage.agentFilter")}
              <select
                aria-label={t("usage.agentFilter")}
                value={agentId ?? ""}
                onChange={(event) => updateParam("agent", event.target.value)}
                className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
              >
                <option value="">{t("usage.allAgents")}</option>
                {(report.data?.filter_options.agents ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {(["today", "7d", "30d", "all"] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => updateParam("range", key, "30d")}
                className={cn(
                  "rounded-xl border bg-card p-4 text-left transition-colors",
                  period === key
                    ? "border-primary/50 bg-primary/5"
                    : "border-border hover:bg-muted/30",
                )}
              >
                <span className="text-xs text-muted-foreground">{t(`usage.periods.${key}`)}</span>
                <strong className="mt-2 block text-xl tabular-nums">
                  {formatCurrency(periodCosts[key], i18n.language)}
                </strong>
              </button>
            ))}
            <div className="rounded-xl border border-border bg-card p-4">
              <span className="text-xs text-muted-foreground">{t("usage.totalTokens")}</span>
              <strong className="mt-2 block text-xl tabular-nums">
                {formatNumber(totalTokens, i18n.language)}
              </strong>
            </div>
          </div>

          <DailyCostTrend
            data={report.data?.daily_cost ?? []}
            language={i18n.language}
            title={t("usage.trend.title")}
            description={t("usage.trend.description")}
            emptyLabel={t("usage.trend.empty")}
            totalLabel={t("usage.trend.total")}
          />

          <div className="mt-8">
            <h2 className="text-base font-semibold">{t("usage.operationsTitle")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t("usage.operationsDescription")}</p>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[
              {
                label: t("usage.metrics.totalRuns"),
                value: formatNumber(operations?.total_runs ?? 0, i18n.language),
                hint: t("usage.metrics.activeRuns", { count: operations?.active_runs ?? 0 }),
              },
              {
                label: t("usage.metrics.successRate"),
                value: formatPercent(operations?.success_rate ?? null, i18n.language),
                hint: t("usage.metrics.terminalRuns", { count: operations?.terminal_runs ?? 0 }),
              },
              {
                label: t("usage.metrics.averageRun"),
                value: formatDuration(operations?.average_run_seconds ?? null, i18n.language, t),
                hint: t("usage.metrics.completedDurationHint"),
              },
              {
                label: t("usage.metrics.retryRate"),
                value: formatPercent(operations?.retry_rate ?? null, i18n.language),
                hint: t("usage.metrics.retryRuns", { count: operations?.retry_runs ?? 0 }),
              },
              {
                label: t("usage.metrics.unpricedRuns"),
                value: formatNumber(operations?.unpriced_runs ?? 0, i18n.language),
                hint: t("usage.metrics.pricedRuns", { count: operations?.priced_runs ?? 0 }),
              },
            ].map((metric) => (
              <div key={metric.label} className="rounded-xl border border-border bg-card p-4">
                <span className="text-xs text-muted-foreground">{metric.label}</span>
                <strong className="mt-2 block text-xl tabular-nums">{metric.value}</strong>
                <span className="mt-1 block text-xs text-muted-foreground">{metric.hint}</span>
              </div>
            ))}
          </div>

          <div className="mt-8 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">{t("usage.breakdownTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("usage.breakdownDescription")}
              </p>
            </div>
            <SegmentedFilter<BreakdownDimension>
              label={t("usage.breakdownLabel")}
              value={dimension}
              onValueChange={(value) => updateParam("by", value, "projects")}
              options={[
                { value: "projects", label: t("usage.breakdowns.projects") },
                { value: "agents", label: t("usage.breakdowns.agents") },
                { value: "runtimes", label: t("usage.breakdowns.runtimes") },
                { value: "skills", label: t("usage.breakdowns.skills") },
              ]}
            />
          </div>
          <div className="mt-4">
            {breakdownRows.length === 0 ? (
              <CollectionState state="empty" title={t("usage.breakdownEmpty")} />
            ) : (
              <EntityTable
                caption={t("usage.breakdownCaption")}
                columns={[
                  { key: "name", label: t(`usage.breakdowns.${dimension}`) },
                  { key: "runs", label: t("usage.breakdownColumns.runs") },
                  { key: "success", label: t("usage.breakdownColumns.success") },
                  { key: "duration", label: t("usage.breakdownColumns.duration") },
                  { key: "tokens", label: t("usage.breakdownColumns.tokens") },
                  {
                    key: "cost",
                    label:
                      dimension === "skills"
                        ? t("usage.breakdownColumns.associatedCost")
                        : t("usage.breakdownColumns.cost"),
                  },
                ]}
              >
                {breakdownRows.map((row) => {
                  const target = breakdownTarget(row);
                  return (
                    <tr key={row.id} className="hover:bg-muted/30">
                      <td className="max-w-64 px-3 py-3">
                        {target ? (
                          <Link to={target} className="font-medium hover:underline">
                            {row.name}
                          </Link>
                        ) : (
                          <span className="font-medium">{row.name}</span>
                        )}
                        {row.uses !== null ? (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("usage.skillUses", { count: row.uses })}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 tabular-nums">
                        {formatNumber(row.run_count, i18n.language)}
                      </td>
                      <td className="px-3 py-3 tabular-nums">
                        {formatPercent(row.success_rate, i18n.language)}
                      </td>
                      <td className="px-3 py-3 tabular-nums text-muted-foreground">
                        {formatDuration(row.average_run_seconds, i18n.language, t)}
                      </td>
                      <td className="px-3 py-3 tabular-nums text-muted-foreground">
                        {formatNumber(row.total_tokens, i18n.language)}
                      </td>
                      <td className="px-3 py-3 tabular-nums">
                        {row.priced_run_count > 0
                          ? formatCurrency(row.cost_usd, i18n.language)
                          : t("usage.unpriced")}
                        {row.unpriced_run_count > 0 ? (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("usage.unpricedRunCount", { count: row.unpriced_run_count })}
                          </p>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </EntityTable>
            )}
          </div>

          <div className="mt-8">
            <h2 className="text-base font-semibold">{t("usage.taskRunsTitle")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t("usage.taskRunsDescription")}</p>
          </div>
          <div className="mt-4">
            {taskRuns.length === 0 ? (
              <CollectionState state="empty" title={t("usage.taskRunsEmpty")} />
            ) : (
              <EntityTable
                caption={t("usage.taskRunsCaption")}
                columns={[
                  { key: "task", label: t("usage.taskRunColumns.task") },
                  { key: "project", label: t("usage.taskRunColumns.project") },
                  { key: "owner", label: t("usage.taskRunColumns.owner") },
                  { key: "state", label: t("usage.taskRunColumns.state") },
                  { key: "duration", label: t("usage.taskRunColumns.duration") },
                  { key: "usage", label: t("usage.taskRunColumns.usage") },
                  { key: "session", label: t("usage.taskRunColumns.session") },
                ]}
              >
                {taskRuns.map((run) => (
                  <tr key={run.id} className="hover:bg-muted/30">
                    <td className="max-w-72 px-3 py-3">
                      <Link
                        to={`/tasks/${run.task_id}#run-${run.id}`}
                        className="block font-medium hover:underline"
                      >
                        {run.task_title}
                      </Link>
                      <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
                        {run.id.slice(0, 12)}
                      </span>
                      {run.failure_message || run.waiting_reason ? (
                        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                          {run.failure_code ? `${run.failure_code}: ` : ""}
                          {run.failure_message || run.waiting_reason}
                        </p>
                      ) : null}
                    </td>
                    <td className="max-w-48 px-3 py-3">
                      {run.project_id ? (
                        <Link to={`/projects/${run.project_id}`} className="hover:underline">
                          {run.project_name || run.project_id}
                        </Link>
                      ) : (
                        t("common.notAvailable")
                      )}
                    </td>
                    <td className="max-w-52 px-3 py-3 text-xs">
                      <Link
                        to={`/multi-agents/${run.agent_id}`}
                        className="block font-medium hover:underline"
                      >
                        {run.agent_name}
                      </Link>
                      <Link
                        to={`/runtime/${run.runtime_id}`}
                        className="mt-1 block text-muted-foreground hover:underline"
                      >
                        {run.runtime_name}
                      </Link>
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-medium">
                        {t(`tasks.detail.runStates.${run.state}`)}
                      </span>
                      {run.trigger === "retry" ? (
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {t("usage.retry")}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 tabular-nums text-muted-foreground">
                      {formatDuration(run.run_seconds, i18n.language, t)}
                      {run.run_duration_live ? (
                        <span className="mt-1 block text-xs">{t("usage.liveDuration")}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 text-xs">
                      <span className="block tabular-nums">
                        {t("usage.tokenValue", {
                          value: formatNumber(run.total_tokens, i18n.language),
                        })}
                      </span>
                      <span className="mt-1 block tabular-nums text-muted-foreground">
                        {run.priced
                          ? formatCurrency(run.cost_usd, i18n.language)
                          : t("usage.unpriced")}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      {run.session_id ? (
                        <Link to={`/c/${run.session_id}`} className="font-medium hover:underline">
                          {t("usage.openSession")}
                        </Link>
                      ) : (
                        t("usage.noSession")
                      )}
                    </td>
                  </tr>
                ))}
              </EntityTable>
            )}
          </div>

          <section
            className="mt-8 rounded-xl border border-border bg-muted/20 p-4"
            aria-labelledby="usage-quality-title"
          >
            <h2 id="usage-quality-title" className="text-sm font-semibold">
              {t("usage.dataQualityTitle")}
            </h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-xs text-muted-foreground">
              <li>{t("usage.dataQuality.successRate")}</li>
              <li>{t("usage.dataQuality.waitingDuration")}</li>
              <li>{t("usage.dataQuality.skillAttribution")}</li>
              <li>{t("usage.dataQuality.unpriced", { count: operations?.unpriced_runs ?? 0 })}</li>
            </ul>
          </section>

          <div className="mt-8">
            <h2 className="text-base font-semibold">{t("usage.sessionsLabel")}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t("usage.sessionsDescription")}</p>
          </div>
          <CollectionToolbar className="mt-4">
            <div className="relative min-w-56 flex-1 sm:max-w-sm">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label={t("common.search")}
                value={search}
                onChange={(event) => updateParam("q", event.target.value)}
                placeholder={t("usage.searchPlaceholder")}
                className="pl-9"
              />
            </div>
          </CollectionToolbar>
          <div className="mt-4">
            {sessions.length === 0 ? (
              <CollectionState
                state="empty"
                title={t("usage.empty")}
                description={t("usage.emptyDescription")}
              />
            ) : filtered.length === 0 ? (
              <CollectionState state="empty" title={t("usage.noMatches")} />
            ) : (
              <EntityTable
                caption={t("usage.tableCaption")}
                columns={[
                  { key: "session", label: t("usage.columns.session") },
                  { key: "models", label: t("usage.columns.models") },
                  { key: "tokens", label: t("usage.columns.tokens") },
                  { key: "cost", label: t("usage.columns.cost") },
                  { key: "updated", label: t("usage.columns.updated") },
                ]}
              >
                {filtered.map((session) => {
                  const models = Object.keys(session.models);
                  return (
                    <tr key={session.id} className="hover:bg-muted/30">
                      <td className="max-w-72 px-3 py-3">
                        <Link
                          to={`/c/${session.id}`}
                          className="block truncate font-medium hover:underline"
                        >
                          {session.title || session.id}
                        </Link>
                      </td>
                      <td className="max-w-72 px-3 py-3 text-xs text-muted-foreground">
                        {models.length > 0 ? models.join(", ") : t("usage.noModels")}
                      </td>
                      <td className="px-3 py-3 tabular-nums text-muted-foreground">
                        {formatNumber(session.total_tokens, i18n.language)}
                      </td>
                      <td className="px-3 py-3 tabular-nums">
                        {session.priced
                          ? formatCurrency(session.cost_usd, i18n.language)
                          : t("usage.unpriced")}
                      </td>
                      <td className="px-3 py-3 text-muted-foreground">
                        {formatDate(session.updated_at, i18n.language)}
                      </td>
                    </tr>
                  );
                })}
              </EntityTable>
            )}
          </div>
        </>
      )}
    </PageScroll>
  );
}
