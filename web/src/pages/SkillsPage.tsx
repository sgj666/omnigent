import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenIcon,
  GitBranchIcon,
  GitCommitHorizontalIcon,
  LockIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageScroll } from "@/components/PageScroll";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  EntityTable,
  SegmentedFilter,
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
import { Link, useSearchParams } from "@/lib/routing";
import {
  getSkillsRepositoryConfig,
  listSkills,
  syncSkills,
  updateSkillsRepositoryConfig,
  type SkillsRepositoryConfig,
  type UpdateSkillsRepositoryConfig,
  type SkillRepositorySource,
  type SkillValidationStatus,
} from "@/lib/skillsApi";

type SkillFilter = "all" | "valid" | "issues";

function validationTone(status: SkillValidationStatus) {
  if (status === "valid") return "success" as const;
  if (status === "warning") return "warning" as const;
  return "danger" as const;
}

function syncTone(status: SkillRepositorySource["sync_status"]) {
  if (status === "current") return "success" as const;
  if (status === "stale") return "warning" as const;
  return "danger" as const;
}

export function SkillsPage() {
  const { t } = useTranslation("management");
  const [params, setParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [repositoryDialogOpen, setRepositoryDialogOpen] = useState(false);
  const inventory = useQuery({
    queryKey: ["skills"],
    queryFn: ({ signal }) => listSkills(signal),
    retry: false,
  });
  const sync = useMutation({
    mutationFn: syncSkills,
    onSuccess: (value) => {
      queryClient.setQueryData(["skills"], value);
      void queryClient.invalidateQueries({ queryKey: ["agent-bundle-options"] });
    },
  });
  const repositoryConfig = useQuery({
    queryKey: ["skills", "repository-config"],
    queryFn: ({ signal }) => getSkillsRepositoryConfig(signal),
    retry: false,
  });
  const updateRepository = useMutation({
    mutationFn: updateSkillsRepositoryConfig,
    onSuccess: (value) => {
      queryClient.setQueryData(["skills", "repository-config"], value.config);
      queryClient.setQueryData(["skills"], value.inventory);
      queryClient.removeQueries({ queryKey: ["skills", "detail"] });
      queryClient.removeQueries({ queryKey: ["skills", "draft"] });
      void queryClient.invalidateQueries({ queryKey: ["agent-bundle-options"] });
      setRepositoryDialogOpen(false);
    },
  });
  const search = params.get("q") ?? "";
  const rawFilter = params.get("status");
  const filter: SkillFilter = rawFilter === "valid" || rawFilter === "issues" ? rawFilter : "all";

  function updateParam(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const skills = useMemo(() => inventory.data?.data ?? [], [inventory.data?.data]);
  const validCount = skills.filter((skill) => skill.validation_status === "valid").length;
  const issueCount = skills.length - validCount;
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return skills.filter((skill) => {
      if (filter === "valid" && skill.validation_status !== "valid") return false;
      if (filter === "issues" && skill.validation_status === "valid") return false;
      if (!needle) return true;
      return [skill.name, skill.description, skill.relative_path].some((value) =>
        value.toLocaleLowerCase().includes(needle),
      );
    });
  }, [filter, search, skills]);

  return (
    <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl" data-testid="skills-page">
      <CollectionPageHeader
        title={t("skills.title")}
        description={t("skills.description")}
        actions={
          <Button
            type="button"
            variant="outline"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            <RefreshCwIcon className={sync.isPending ? "animate-spin" : undefined} />
            {sync.isPending ? t("skills.syncing") : t("skills.sync")}
          </Button>
        }
      />

      {inventory.isLoading ? (
        <CollectionState className="mt-6" state="loading" title={t("skills.loading")} />
      ) : inventory.isError ? (
        <CollectionState
          className="mt-6"
          state="error"
          title={t("skills.error")}
          description={inventory.error instanceof Error ? inventory.error.message : undefined}
          action={
            <Button type="button" variant="outline" onClick={() => void inventory.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : inventory.data ? (
        <>
          <RepositorySummary
            source={inventory.data.source}
            config={repositoryConfig.data}
            onEdit={() => setRepositoryDialogOpen(true)}
          />
          {sync.isError ? (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {sync.error instanceof Error ? sync.error.message : t("skills.error")}
            </p>
          ) : null}
          <CollectionToolbar className="mt-6" label={t("skills.controls")}>
            <div className="relative min-w-56 flex-1 sm:max-w-sm">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label={t("common.search")}
                value={search}
                onChange={(event) => updateParam("q", event.target.value)}
                placeholder={t("skills.searchPlaceholder")}
                className="pl-9"
              />
            </div>
            <SegmentedFilter<SkillFilter>
              label={t("skills.filterLabel")}
              value={filter}
              onValueChange={(value) => updateParam("status", value, "all")}
              options={[
                { value: "all", label: t("skills.filters.all"), count: skills.length },
                { value: "valid", label: t("skills.filters.valid"), count: validCount },
                { value: "issues", label: t("skills.filters.issues"), count: issueCount },
              ]}
            />
          </CollectionToolbar>

          <div className="mt-4">
            {skills.length === 0 ? (
              <CollectionState
                state={inventory.data.source.sync_status === "current" ? "empty" : "error"}
                title={
                  inventory.data.source.sync_status === "current"
                    ? t("skills.empty")
                    : t(`skills.syncStatus.${inventory.data.source.sync_status}`)
                }
                description={inventory.data.source.error ?? t("skills.emptyDescription")}
              />
            ) : filtered.length === 0 ? (
              <CollectionState state="empty" title={t("skills.noMatches")} />
            ) : (
              <EntityTable
                caption={t("skills.tableCaption")}
                columns={[
                  { key: "skill", label: t("skills.columns.skill") },
                  { key: "status", label: t("skills.columns.status") },
                  { key: "files", label: t("skills.columns.files") },
                  { key: "path", label: t("skills.columns.path") },
                  { key: "version", label: t("skills.columns.version") },
                ]}
              >
                {filtered.map((skill) => (
                  <tr key={skill.id} className="hover:bg-muted/30">
                    <td className="max-w-80 px-3 py-3">
                      <Link
                        to={`/skills/${skill.id}`}
                        className="block font-medium hover:underline"
                      >
                        {skill.name}
                      </Link>
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                        {skill.description || t("skills.noDescription")}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone={validationTone(skill.validation_status)}>
                        {t(`skills.validation.${skill.validation_status}`)}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-3 tabular-nums text-muted-foreground">
                      {skill.file_count}
                    </td>
                    <td className="max-w-64 px-3 py-3">
                      <code className="block truncate text-xs text-muted-foreground">
                        {skill.relative_path}
                      </code>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-muted-foreground">
                      {inventory.data.source.commit_sha?.slice(0, 12) ?? "—"}
                    </td>
                  </tr>
                ))}
              </EntityTable>
            )}
          </div>
        </>
      ) : null}
      {repositoryConfig.data ? (
        <RepositoryConfigDialog
          open={repositoryDialogOpen}
          onOpenChange={setRepositoryDialogOpen}
          config={repositoryConfig.data}
          pending={updateRepository.isPending}
          error={
            updateRepository.isError && updateRepository.error instanceof Error
              ? updateRepository.error.message
              : null
          }
          onSubmit={(value) => updateRepository.mutate(value)}
        />
      ) : null}
    </PageScroll>
  );
}

function RepositorySummary({
  source,
  config,
  onEdit,
}: {
  source: SkillRepositorySource;
  config?: SkillsRepositoryConfig;
  onEdit: () => void;
}) {
  const { t } = useTranslation("management");
  return (
    <section
      className="mt-6 rounded-xl border bg-card p-4"
      aria-label={t("skills.repositoryTitle")}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
            <BookOpenIcon className="size-4 text-muted-foreground" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">{t("skills.repositoryTitle")}</h2>
            <p className="mt-1 break-all text-xs text-muted-foreground">
              {source.remote_url || t("skills.notConfigured")}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {config?.editable ? (
            <Button type="button" variant="outline" size="sm" onClick={onEdit}>
              {t("skills.editRepository")}
            </Button>
          ) : null}
          <StatusBadge tone={syncTone(source.sync_status)}>
            {t(`skills.syncStatus.${source.sync_status}`)}
          </StatusBadge>
          <StatusBadge tone="neutral">
            <LockIcon className="mr-1 size-3" />
            {t("skills.readOnly")}
          </StatusBadge>
        </div>
      </div>
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-3">
        <div>
          <dt className="flex items-center gap-1 text-muted-foreground">
            <GitBranchIcon className="size-3" /> {t("skills.ref")}
          </dt>
          <dd className="mt-1 font-mono">{source.ref}</dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-muted-foreground">
            <GitCommitHorizontalIcon className="size-3" /> {t("skills.commit")}
          </dt>
          <dd className="mt-1 font-mono">{source.commit_sha?.slice(0, 12) ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("skills.rootPath")}</dt>
          <dd className="mt-1 font-mono">{source.skills_path}</dd>
        </div>
      </dl>
      {source.error ? <p className="mt-3 text-xs text-warning">{source.error}</p> : null}
    </section>
  );
}

function RepositoryConfigDialog({
  open,
  onOpenChange,
  config,
  pending,
  error,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  config: SkillsRepositoryConfig;
  pending: boolean;
  error: string | null;
  onSubmit: (value: UpdateSkillsRepositoryConfig) => void;
}) {
  const { t } = useTranslation("management");
  const [url, setUrl] = useState(config.url);
  const [ref, setRef] = useState(config.ref);
  const [path, setPath] = useState(config.path);
  const [username, setUsername] = useState(config.username ?? "");
  const [token, setToken] = useState("");

  useEffect(() => {
    if (!open) return;
    setUrl(config.url);
    setRef(config.ref);
    setPath(config.path);
    setUsername(config.username ?? "");
    setToken("");
  }, [config, open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value: UpdateSkillsRepositoryConfig = {
      url: url.trim(),
      ref: ref.trim(),
      path: path.trim(),
      username: username.trim() || null,
    };
    if (token) value.token = token;
    onSubmit(value);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("skills.repositoryDialogTitle")}</DialogTitle>
          <DialogDescription>{t("skills.repositoryDialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <RepositoryField
            id="skills-repository-url"
            label={t("skills.repositoryUrl")}
            value={url}
            onChange={setUrl}
            disabled={pending}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <RepositoryField
              id="skills-repository-ref"
              label={t("skills.repositoryRef")}
              value={ref}
              onChange={setRef}
              disabled={pending}
            />
            <RepositoryField
              id="skills-repository-path"
              label={t("skills.repositoryPath")}
              value={path}
              onChange={setPath}
              disabled={pending}
            />
          </div>
          <RepositoryField
            id="skills-repository-username"
            label={t("skills.repositoryUsername")}
            value={username}
            onChange={setUsername}
            disabled={pending}
            required={false}
          />
          <div className="space-y-1.5">
            <label htmlFor="skills-repository-token" className="text-sm font-medium">
              {t("skills.repositoryToken")}
            </label>
            <Input
              id="skills-repository-token"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              disabled={pending}
              autoComplete="new-password"
            />
            {config.token_configured ? (
              <p className="text-xs text-muted-foreground">
                {t("skills.tokenConfiguredPlaceholder")}
              </p>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={pending || !url.trim() || !ref.trim() || !path.trim()}>
              {pending ? t("skills.savingRepository") : t("skills.saveRepository")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RepositoryField({
  id,
  label,
  value,
  onChange,
  disabled,
  required = true,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  required?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        required={required}
      />
    </div>
  );
}
