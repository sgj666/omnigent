import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BotIcon,
  DownloadIcon,
  FileTextIcon,
  FolderIcon,
  GitBranchIcon,
  LaptopIcon,
  PlusIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageBackButton } from "@/components/PageBackButton";
import { PageScroll } from "@/components/PageScroll";
import { CollectionState, EntityTable, StatusBadge } from "@/components/collection";
import { Button } from "@/components/ui/button";
import { useProjectSessions } from "@/hooks/useConversations";
import { getProject, listProjectArtifacts } from "@/lib/projectsApi";
import { Link, useParams } from "@/lib/routing";

function timestampLabel(value: number | null | undefined, language: string): string {
  if (value == null) return "—";
  const date = new Date(value < 10_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function sessionTone(status: "idle" | "running" | "failed" | undefined) {
  if (status === "running") return "info" as const;
  if (status === "failed") return "danger" as const;
  return "neutral" as const;
}

function bytesLabel(value: number | null, language: string): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value.toLocaleString(language)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  for (const unit of units) {
    if (amount < 1024 || unit === units.at(-1)) {
      return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${unit}`;
    }
    amount /= 1024;
  }
  return `${value.toLocaleString(language)} B`;
}

export function ProjectDetailPage() {
  const { t, i18n } = useTranslation("management");
  const { projectId } = useParams<{ projectId: string }>();
  const project = useQuery({
    queryKey: ["projects", "detail", projectId],
    queryFn: () => getProject(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  });
  const artifacts = useQuery({
    queryKey: ["projects", "detail", projectId, "artifacts"],
    queryFn: () => listProjectArtifacts(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  });
  const sessions = useProjectSessions(project.data?.name ?? "", Boolean(project.data));
  const rows = useMemo(
    () => sessions.data?.pages.flatMap((page) => page.data) ?? [],
    [sessions.data],
  );

  if (project.isLoading) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <CollectionState state="loading" title={t("projects.detail.loading")} />
      </PageScroll>
    );
  }

  if (project.isError || !project.data) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <PageBackButton fallbackTo="/projects" className="mb-4">
          {t("projects.detail.back")}
        </PageBackButton>
        <CollectionState state="error" title={t("projects.detail.notFound")} />
      </PageScroll>
    );
  }

  const value = project.data;
  const defaults = value.config ?? {};

  return (
    <PageScroll
      contentClassName="px-6"
      maxWidthClassName="max-w-6xl"
      data-testid="project-detail-page"
    >
      <PageBackButton fallbackTo="/projects" className="mb-4">
        {t("projects.detail.back")}
      </PageBackButton>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border bg-card">
            <FolderIcon className="size-5 text-muted-foreground" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-2xl font-semibold tracking-tight">{value.name}</h1>
              <StatusBadge tone="success">{t("projects.status.ready")}</StatusBadge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("projects.detail.summary", { count: value.session_count ?? 0 })}
            </p>
          </div>
        </div>
        <Button asChild>
          <Link to={{ pathname: "/", search: `?project=${encodeURIComponent(value.name)}` }}>
            <PlusIcon />
            {t("projects.newSession")}
          </Link>
        </Button>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-8">
          <section>
            <div className="mb-3">
              <h2 className="text-sm font-semibold">{t("projects.detail.sessionsTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("projects.detail.sessionsDescription")}
              </p>
            </div>
            {sessions.isLoading ? (
              <CollectionState state="loading" title={t("projects.detail.sessionsLoading")} />
            ) : sessions.isError ? (
              <CollectionState state="error" title={t("projects.detail.sessionsError")} />
            ) : rows.length === 0 ? (
              <CollectionState
                state="empty"
                title={t("projects.detail.sessionsEmpty")}
                description={t("projects.detail.sessionsEmptyDescription")}
              />
            ) : (
              <>
                <EntityTable
                  caption={t("projects.detail.sessionsCaption")}
                  columns={[
                    { key: "session", label: t("projects.detail.columns.session") },
                    { key: "agent", label: t("projects.detail.columns.agent") },
                    { key: "runtime", label: t("projects.detail.columns.runtime") },
                    { key: "status", label: t("projects.detail.columns.status") },
                    { key: "updated", label: t("projects.detail.columns.updated") },
                  ]}
                >
                  {rows.map((session) => (
                    <tr key={session.id} className="hover:bg-muted/30">
                      <td className="px-3 py-3">
                        <Link to={`/c/${session.id}`} className="font-medium hover:underline">
                          {session.title || t("projects.detail.untitledSession")}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-muted-foreground">
                        {session.agent_name ?? session.agent_id ?? "—"}
                      </td>
                      <td className="max-w-48 px-3 py-3 text-xs text-muted-foreground">
                        <span className="block truncate">
                          {session.workspace ?? session.host_id ?? "—"}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <StatusBadge tone={sessionTone(session.status)}>
                          {t(`projects.detail.sessionStatus.${session.status ?? "idle"}`)}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-3 text-muted-foreground">
                        {timestampLabel(session.updated_at, i18n.language)}
                      </td>
                    </tr>
                  ))}
                </EntityTable>
                {sessions.hasNextPage ? (
                  <Button
                    variant="outline"
                    className="mt-3"
                    loading={sessions.isFetchingNextPage}
                    onClick={() => void sessions.fetchNextPage()}
                  >
                    {t("projects.detail.loadMore")}
                  </Button>
                ) : null}
              </>
            )}
          </section>

          <section data-testid="project-artifacts">
            <div className="mb-3">
              <h2 className="text-sm font-semibold">{t("projects.detail.artifactsTitle")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("projects.detail.artifactsDescription")}
              </p>
            </div>
            {artifacts.isLoading ? (
              <CollectionState state="loading" title={t("projects.detail.artifactsLoading")} />
            ) : artifacts.isError ? (
              <CollectionState state="error" title={t("projects.detail.artifactsError")} />
            ) : artifacts.data?.length === 0 ? (
              <CollectionState
                state="empty"
                title={t("projects.detail.artifactsEmpty")}
                description={t("projects.detail.artifactsEmptyDescription")}
              />
            ) : (
              <EntityTable
                caption={t("projects.detail.artifactsCaption")}
                columns={[
                  { key: "file", label: t("projects.detail.artifactColumns.file") },
                  { key: "source", label: t("projects.detail.artifactColumns.source") },
                  { key: "summary", label: t("projects.detail.artifactColumns.summary") },
                  { key: "version", label: t("projects.detail.artifactColumns.version") },
                  { key: "visibility", label: t("projects.detail.artifactColumns.visibility") },
                  { key: "created", label: t("projects.detail.artifactColumns.created") },
                ]}
              >
                {artifacts.data?.map((artifact) => (
                  <tr key={`${artifact.work_item_run_id}:${artifact.id}`} className="align-top">
                    <td className="px-3 py-3">
                      <div className="flex min-w-44 items-start gap-2">
                        <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          {artifact.available && artifact.download_url ? (
                            <a
                              href={artifact.download_url}
                              className="inline-flex max-w-full items-center gap-1 font-medium hover:underline"
                              title={t("projects.detail.downloadArtifact", { name: artifact.name })}
                            >
                              <span className="truncate">{artifact.name}</span>
                              <DownloadIcon className="size-3 shrink-0" />
                            </a>
                          ) : (
                            <span className="font-medium">{artifact.name}</span>
                          )}
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {artifact.content_type ?? t("common.unknown")} ·{" "}
                            {bytesLabel(artifact.bytes, i18n.language)}
                          </p>
                          {!artifact.available ? (
                            <p className="mt-1 text-xs text-destructive">
                              {t("projects.detail.artifactUnavailable")}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        to={`/tasks/${artifact.work_item_id}#run-${artifact.work_item_run_id}`}
                        className="font-medium hover:underline"
                      >
                        {artifact.work_item_title}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span>
                          {t("projects.detail.artifactRun", {
                            id: artifact.work_item_run_id.slice(0, 8),
                          })}
                        </span>
                        {artifact.session_id ? (
                          <Link to={`/c/${artifact.session_id}`} className="hover:text-foreground">
                            {t("projects.detail.artifactSession")}
                          </Link>
                        ) : null}
                      </div>
                    </td>
                    <td className="max-w-64 px-3 py-3 text-muted-foreground">
                      <p className="line-clamp-3">
                        {artifact.summary ?? t("projects.detail.artifactNoSummary")}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone="neutral">
                        {t("projects.detail.artifactVersion", { version: artifact.version })}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone="neutral">
                        {t("projects.detail.artifactPrivate")}
                      </StatusBadge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-muted-foreground">
                      {timestampLabel(artifact.created_at, i18n.language)}
                    </td>
                  </tr>
                ))}
              </EntityTable>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <section className="rounded-xl border bg-card">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold">{t("projects.detail.defaultsTitle")}</h2>
            </div>
            <dl className="divide-y text-sm">
              <DetailRow
                icon={<BotIcon />}
                label={t("projects.detail.defaultAgent")}
                value={defaults.agent_id}
              />
              <DetailRow
                icon={<LaptopIcon />}
                label={t("projects.detail.defaultRuntime")}
                value={defaults.host_id}
              />
              <DetailRow
                icon={<FolderIcon />}
                label={t("projects.detail.defaultWorkspace")}
                value={defaults.workspace}
              />
              <DetailRow
                icon={<GitBranchIcon />}
                label={t("projects.detail.defaultWorktree")}
                value={defaults.use_worktree ? t("projects.detail.enabled") : undefined}
              />
            </dl>
          </section>
          <section className="rounded-xl border bg-card p-4 text-sm">
            <h2 className="font-semibold">{t("projects.detail.metadataTitle")}</h2>
            <dl className="mt-3 space-y-3">
              <MetaRow
                label={t("projects.detail.created")}
                value={timestampLabel(value.created_at, i18n.language)}
              />
              <MetaRow
                label={t("projects.detail.updated")}
                value={timestampLabel(value.updated_at, i18n.language)}
              />
              <MetaRow label={t("projects.detail.projectId")} value={value.id} mono />
            </dl>
          </section>
        </aside>
      </div>
    </PageScroll>
  );
}

function DetailRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value?: string;
}) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</span>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 truncate">{value || "—"}</dd>
      </div>
    </div>
  );
}

function MetaRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "mt-0.5 break-all font-mono text-xs" : "mt-0.5"}>{value}</dd>
    </div>
  );
}
