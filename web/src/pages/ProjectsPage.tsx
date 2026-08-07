import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { FolderIcon, SearchIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageScroll } from "@/components/PageScroll";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  EntityRowMenu,
  EntityTable,
  SegmentedFilter,
  StatusBadge,
} from "@/components/collection";
import { Input } from "@/components/ui/input";
import { useProjects } from "@/hooks/useConversations";
import { isPermissionDenied } from "@/lib/httpErrors";
import { listProjects, type Project } from "@/lib/projectsApi";
import { Link, useNavigate, useSearchParams } from "@/lib/routing";

type ProjectFilter = "all" | "active" | "empty";
type ProjectSort = "activity" | "name" | "sessions";
type ProjectRow = Project & { legacy: boolean };

function timestampLabel(value: number | null | undefined, language: string): string {
  if (value == null) return "—";
  const date = new Date(value < 10_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(language).format(date);
}

export function ProjectsPage() {
  const { t, i18n } = useTranslation("management");
  const { t: commonT } = useTranslation("common");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const folders = useProjects();
  const projects = useQuery({
    queryKey: ["projects", "collection"],
    queryFn: listProjects,
  });
  const search = params.get("q") ?? "";
  const rawFilter = params.get("status");
  const filter: ProjectFilter = rawFilter === "active" || rawFilter === "empty" ? rawFilter : "all";
  const rawSort = params.get("sort");
  const sort: ProjectSort = rawSort === "name" || rawSort === "sessions" ? rawSort : "activity";

  function updateParam(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const rows = useMemo<ProjectRow[]>(() => {
    const firstClass = new Map((projects.data ?? []).map((project) => [project.id, project]));
    return (folders.data ?? []).map((folder) => {
      const project = folder.id ? firstClass.get(folder.id) : undefined;
      return project
        ? { ...project, legacy: false }
        : {
            id: folder.id ?? `legacy:${folder.name}`,
            name: folder.name,
            legacy: true,
          };
    });
  }, [folders.data, projects.data]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(i18n.language);
    return rows
      .filter((row) => {
        if (filter === "active" && !(row.session_count && row.session_count > 0)) return false;
        if (filter === "empty" && row.session_count !== 0) return false;
        return !query || row.name.toLocaleLowerCase(i18n.language).includes(query);
      })
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name, i18n.language);
        if (sort === "sessions") {
          return (
            (b.session_count ?? -1) - (a.session_count ?? -1) ||
            a.name.localeCompare(b.name, i18n.language)
          );
        }
        const activityA = a.updated_at ?? a.created_at ?? 0;
        const activityB = b.updated_at ?? b.created_at ?? 0;
        return activityB - activityA || a.name.localeCompare(b.name, i18n.language);
      });
  }, [filter, i18n.language, rows, search, sort]);

  const loading = folders.isLoading || projects.isLoading;
  const failed = folders.isError || projects.isError;
  const permissionDenied = isPermissionDenied(folders.error) || isPermissionDenied(projects.error);

  return (
    <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl" data-testid="projects-page">
      <CollectionPageHeader title={t("projects.title")} description={t("projects.description")} />
      <CollectionToolbar className="mt-6">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label={t("common.search")}
            value={search}
            onChange={(event) => updateParam("q", event.target.value)}
            placeholder={t("projects.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <SegmentedFilter<ProjectFilter>
          label={t("projects.filterLabel")}
          value={filter}
          onValueChange={(value) => updateParam("status", value, "all")}
          options={[
            { value: "all", label: t("projects.filters.all"), count: rows.length },
            {
              value: "active",
              label: t("projects.filters.active"),
              count: rows.filter((row) => (row.session_count ?? 0) > 0).length,
            },
            {
              value: "empty",
              label: t("projects.filters.empty"),
              count: rows.filter((row) => row.session_count === 0).length,
            },
          ]}
        />
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="sr-only">{t("projects.sortLabel")}</span>
          <select
            aria-label={t("projects.sortLabel")}
            value={sort}
            onChange={(event) => updateParam("sort", event.target.value, "activity")}
            className="h-8 rounded-lg border bg-background px-2 text-sm text-foreground"
          >
            <option value="activity">{t("projects.sort.activity")}</option>
            <option value="name">{t("projects.sort.name")}</option>
            <option value="sessions">{t("projects.sort.sessions")}</option>
          </select>
        </label>
      </CollectionToolbar>

      <div className="mt-4">
        {loading ? (
          <CollectionState state="loading" title={t("projects.loading")} />
        ) : failed ? (
          <CollectionState
            state="error"
            title={permissionDenied ? commonT("collection.permissionDenied") : t("projects.error")}
            description={
              permissionDenied ? commonT("collection.permissionDeniedDescription") : undefined
            }
            action={
              <button
                type="button"
                className="text-sm font-medium text-primary"
                onClick={() => void Promise.all([folders.refetch(), projects.refetch()])}
              >
                {t("common.retry")}
              </button>
            }
          />
        ) : rows.length === 0 ? (
          <CollectionState
            state="empty"
            title={t("projects.empty")}
            description={t("projects.emptyDescription")}
          />
        ) : filtered.length === 0 ? (
          <CollectionState state="empty" title={t("projects.noMatches")} />
        ) : (
          <EntityTable
            caption={t("projects.tableCaption")}
            columns={[
              { key: "name", label: t("projects.columns.name") },
              { key: "sessions", label: t("projects.columns.sessions") },
              { key: "artifacts", label: t("projects.columns.artifacts") },
              { key: "defaults", label: t("projects.columns.defaults") },
              { key: "updated", label: t("projects.columns.updated") },
              { key: "status", label: t("projects.columns.status") },
              { key: "actions", label: <span className="sr-only">{t("common.actions")}</span> },
            ]}
          >
            {filtered.map((project) => {
              const defaults = [
                project.config?.agent_id
                  ? t("projects.defaultAgent", { value: project.config.agent_id })
                  : null,
                project.config?.host_id
                  ? t("projects.defaultRuntime", { value: project.config.host_id })
                  : null,
              ].filter(Boolean);
              return (
                <tr key={project.id} className="hover:bg-muted/30">
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                        <FolderIcon className="size-4 text-muted-foreground" />
                      </span>
                      {project.legacy ? (
                        <span className="min-w-0 truncate font-medium">{project.name}</span>
                      ) : (
                        <Link
                          to={`/projects/${encodeURIComponent(project.id)}`}
                          className="min-w-0 truncate font-medium hover:underline"
                        >
                          {project.name}
                        </Link>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-muted-foreground">
                    {project.session_count == null
                      ? "—"
                      : t("projects.sessionCount", { count: project.session_count })}
                  </td>
                  <td className="max-w-56 px-3 py-3 text-xs text-muted-foreground">
                    {project.artifact_count == null
                      ? "—"
                      : project.artifact_count === 0
                        ? t("projects.noArtifacts")
                        : t("projects.artifactSummary", {
                            count: project.artifact_count,
                            name: project.latest_artifact_name,
                          })}
                  </td>
                  <td className="max-w-64 px-3 py-3 text-xs text-muted-foreground">
                    {defaults.length > 0 ? defaults.join(" · ") : t("projects.noDefaults")}
                  </td>
                  <td className="px-3 py-3 text-muted-foreground">
                    {timestampLabel(project.updated_at ?? project.created_at, i18n.language)}
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge tone={project.legacy ? "warning" : "success"}>
                      {t(project.legacy ? "projects.status.legacy" : "projects.status.ready")}
                    </StatusBadge>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <EntityRowMenu
                      label={`${project.name} ${t("common.actions")}`}
                      actions={[
                        {
                          id: "new-session",
                          label: t("projects.newSession"),
                          onSelect: () =>
                            navigate({
                              pathname: "/",
                              search: `?project=${encodeURIComponent(project.name)}`,
                            }),
                        },
                      ]}
                    />
                  </td>
                </tr>
              );
            })}
          </EntityTable>
        )}
      </div>
    </PageScroll>
  );
}
