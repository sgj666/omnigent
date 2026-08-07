import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BanIcon,
  FileTextIcon,
  FolderGit2Icon,
  GitCompareArrowsIcon,
  GitBranchIcon,
  GitCommitHorizontalIcon,
  LockIcon,
  SaveIcon,
  ShieldCheckIcon,
  Trash2Icon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageBackButton } from "@/components/PageBackButton";
import { PageScroll } from "@/components/PageScroll";
import { CollectionState, StatusBadge } from "@/components/collection";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  discardSkillDraft,
  dryRunSkillDraft,
  getSkill,
  getSkillDraft,
  saveSkillDraft,
  validateSkillDraft,
  type SkillDryRun,
  type SkillFile,
  type SkillValidationStatus,
} from "@/lib/skillsApi";
import { useParams } from "@/lib/routing";
import { cn } from "@/lib/utils";

function validationTone(status: SkillValidationStatus) {
  if (status === "valid") return "success" as const;
  if (status === "warning") return "warning" as const;
  return "danger" as const;
}

export function SkillDetailPage() {
  const { t } = useTranslation("management");
  const { skillId } = useParams<{ skillId: string }>();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["skills", "detail", skillId],
    queryFn: ({ signal }) => getSkill(skillId as string, signal),
    enabled: Boolean(skillId),
    retry: false,
  });
  const draft = useQuery({
    queryKey: ["skills", "draft", skillId],
    queryFn: ({ signal }) => getSkillDraft(skillId as string, signal),
    enabled: Boolean(skillId && detail.data),
    retry: false,
  });
  const [selectedPath, setSelectedPath] = useState("SKILL.md");
  const [draftFiles, setDraftFiles] = useState<SkillFile[]>([]);
  const [dryRun, setDryRun] = useState<SkillDryRun | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!detail.data?.files.some((file) => file.path === selectedPath)) {
      setSelectedPath(detail.data?.files[0]?.path ?? "SKILL.md");
    }
  }, [detail.data?.files, selectedPath]);

  useEffect(() => {
    const files = draft.data?.draft?.files ?? detail.data?.files;
    if (files) setDraftFiles(files);
  }, [detail.data?.files, draft.data?.draft?.files]);

  const refreshDraft = () =>
    queryClient.invalidateQueries({ queryKey: ["skills", "draft", skillId] });
  const saveDraft = useMutation({
    mutationFn: (files: SkillFile[]) => saveSkillDraft(skillId as string, files),
    onSuccess: async () => {
      setActionError(null);
      await refreshDraft();
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : String(error)),
  });
  const validateDraft = useMutation({
    mutationFn: async () => {
      await saveSkillDraft(skillId as string, draftFiles);
      return validateSkillDraft(skillId as string);
    },
    onSuccess: async () => {
      setActionError(null);
      await refreshDraft();
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : String(error)),
  });
  const runDryRun = useMutation({
    mutationFn: async () => {
      await saveSkillDraft(skillId as string, draftFiles);
      return dryRunSkillDraft(skillId as string);
    },
    onSuccess: (result) => {
      setActionError(null);
      setDryRun(result);
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : String(error)),
  });
  const discardDraft = useMutation({
    mutationFn: () => discardSkillDraft(skillId as string),
    onSuccess: async () => {
      setActionError(null);
      setDryRun(null);
      setDraftFiles(detail.data?.files ?? []);
      await refreshDraft();
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : String(error)),
  });

  if (detail.isLoading) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <CollectionState state="loading" title={t("skills.detail.loading")} />
      </PageScroll>
    );
  }
  if (detail.isError || !detail.data) {
    return (
      <PageScroll contentClassName="px-6" maxWidthClassName="max-w-6xl">
        <PageBackButton fallbackTo="/skills" className="mb-4">
          {t("skills.detail.back")}
        </PageBackButton>
        <CollectionState state="error" title={t("skills.detail.notFound")} />
      </PageScroll>
    );
  }

  const skill = detail.data;
  const hasDraft = Boolean(draft.data?.draft);
  const visibleFiles = hasDraft ? draftFiles : skill.files;
  const selected = visibleFiles.find((file) => file.path === selectedPath) ?? visibleFiles[0];
  const draftValidation = draft.data?.draft?.validation;
  const busy =
    saveDraft.isPending || validateDraft.isPending || runDryRun.isPending || discardDraft.isPending;
  return (
    <PageScroll
      contentClassName="px-6"
      maxWidthClassName="max-w-6xl"
      data-testid="skill-detail-page"
    >
      <PageBackButton fallbackTo="/skills" className="mb-4">
        {t("skills.detail.back")}
      </PageBackButton>

      <div className="flex min-w-0 items-start gap-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border bg-card">
          <FolderGit2Icon className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{skill.name}</h1>
            <StatusBadge tone={validationTone(skill.validation_status)}>
              {t(`skills.validation.${skill.validation_status}`)}
            </StatusBadge>
            <StatusBadge tone="neutral">
              <LockIcon className="mr-1 size-3" /> {t("skills.readOnly")}
            </StatusBadge>
            {hasDraft ? (
              <StatusBadge tone="info">{t("skills.detail.draft.local")}</StatusBadge>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {skill.description || t("skills.noDescription")}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {hasDraft ? (
            <>
              <Button size="sm" onClick={() => saveDraft.mutate(draftFiles)} disabled={busy}>
                <SaveIcon /> {t("skills.detail.draft.save")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => validateDraft.mutate()}
                disabled={busy}
              >
                <ShieldCheckIcon /> {t("skills.detail.draft.validate")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => runDryRun.mutate()}
                disabled={busy}
              >
                <GitCompareArrowsIcon /> {t("skills.detail.draft.dryRun")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => discardDraft.mutate()}
                disabled={busy}
              >
                <Trash2Icon /> {t("skills.detail.draft.discard")}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              onClick={() => saveDraft.mutate(skill.files)}
              disabled={busy || draft.isLoading}
            >
              <FileTextIcon /> {t("skills.detail.draft.create")}
            </Button>
          )}
          <Button size="sm" variant="outline" disabled>
            <BanIcon /> {t("skills.detail.draft.publishDisabled")}
          </Button>
        </div>
      </div>

      {actionError ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          {actionError}
        </p>
      ) : null}
      {hasDraft && draft.data?.baseline_current === false ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-warning/30 bg-warning/5 p-3 text-sm"
        >
          {t("skills.detail.draft.stale")}
        </p>
      ) : null}

      <div className="mt-6 grid min-h-[520px] gap-4 lg:grid-cols-[220px_minmax(0,1fr)_280px]">
        <section className="rounded-xl border bg-card p-2">
          <h2 className="px-2 py-2 text-xs font-semibold text-muted-foreground">
            {t("skills.detail.files", { count: skill.file_count })}
          </h2>
          <div className="space-y-0.5">
            {visibleFiles.map((file) => (
              <button
                key={file.path}
                type="button"
                onClick={() => setSelectedPath(file.path)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs",
                  selected?.path === file.path
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <FileTextIcon className="size-3.5 shrink-0" />
                <span className="truncate">{file.path}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="min-w-0 overflow-hidden rounded-xl border bg-card">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <h2 className="truncate font-mono text-xs font-medium">{selected?.path ?? "—"}</h2>
            <span className="text-xs text-muted-foreground">
              {selected ? t("skills.detail.bytes", { count: selected.size }) : null}
            </span>
          </div>
          {selected ? (
            hasDraft ? (
              <Textarea
                aria-label={t("skills.detail.draft.editor", { file: selected.path })}
                value={selected.content}
                onChange={(event) => {
                  const content = event.target.value;
                  setDraftFiles((current) =>
                    current.map((file) =>
                      file.path === selected.path
                        ? { ...file, content, size: new TextEncoder().encode(content).length }
                        : file,
                    ),
                  );
                }}
                className="h-[470px] resize-none rounded-none border-0 p-4 font-mono text-xs leading-5 focus-visible:ring-0"
              />
            ) : (
              <pre className="h-[470px] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5">
                {selected.content}
              </pre>
            )
          ) : (
            <CollectionState className="m-4" state="empty" title={t("skills.detail.noFiles")} />
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-xl border bg-card">
            <div className="border-b px-4 py-3">
              <h2 className="text-sm font-semibold">{t("skills.detail.metadata")}</h2>
            </div>
            <dl className="divide-y text-xs">
              <Fact icon={<GitBranchIcon />} label={t("skills.ref")} value={skill.source.ref} />
              <Fact
                icon={<GitCommitHorizontalIcon />}
                label={t("skills.commit")}
                value={skill.source.commit_sha?.slice(0, 12) ?? "—"}
              />
              <Fact
                icon={<FolderGit2Icon />}
                label={t("skills.columns.path")}
                value={skill.relative_path}
              />
            </dl>
          </section>
          {skill.diagnostics.length > 0 ? (
            <section className="rounded-xl border border-warning/30 bg-warning/5 p-4">
              <h2 className="text-sm font-semibold">{t("skills.detail.diagnostics")}</h2>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                {skill.diagnostics.map((diagnostic) => (
                  <li key={diagnostic}>{diagnostic}</li>
                ))}
              </ul>
            </section>
          ) : null}
          {draftValidation ? (
            <section className="rounded-xl border bg-card p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold">{t("skills.detail.draft.validation")}</h2>
                <StatusBadge tone={validationTone(draftValidation.status)}>
                  {t(`skills.validation.${draftValidation.status}`)}
                </StatusBadge>
              </div>
              {draftValidation.diagnostics.length > 0 ? (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                  {draftValidation.diagnostics.map((diagnostic) => (
                    <li key={diagnostic}>{diagnostic}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("skills.detail.draft.validationPassed")}
                </p>
              )}
            </section>
          ) : null}
          <section className="rounded-xl border bg-muted/20 p-4 text-xs text-muted-foreground">
            {t("skills.detail.draft.safety")}
          </section>
        </aside>
      </div>

      <Dialog open={dryRun !== null} onOpenChange={(open) => !open && setDryRun(null)}>
        <DialogContent className="max-h-[85vh] sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{t("skills.detail.draft.dryRunTitle")}</DialogTitle>
            <DialogDescription>{t("skills.detail.draft.dryRunDescription")}</DialogDescription>
          </DialogHeader>
          {dryRun ? (
            <div className="min-h-0 space-y-3 overflow-auto">
              <dl className="grid gap-2 rounded-lg border bg-muted/20 p-3 text-xs sm:grid-cols-2">
                <Fact
                  icon={<FolderGit2Icon />}
                  label={t("skills.repositoryTitle")}
                  value={dryRun.remote_url}
                />
                <Fact icon={<GitBranchIcon />} label={t("skills.ref")} value={dryRun.ref} />
                <Fact
                  icon={<GitCommitHorizontalIcon />}
                  label={t("skills.detail.draft.baseline")}
                  value={dryRun.baseline_sha}
                />
                <Fact
                  icon={<FileTextIcon />}
                  label={t("skills.columns.path")}
                  value={dryRun.relative_path}
                />
              </dl>
              <p className="text-xs text-muted-foreground">
                {t("skills.detail.draft.changedFiles", { count: dryRun.changed_files.length })}
              </p>
              <pre className="max-h-[52vh] overflow-auto rounded-lg border bg-background p-4 font-mono text-xs leading-5">
                {dryRun.diff || t("skills.detail.draft.noChanges")}
              </pre>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDryRun(null)}>
              {t("skills.detail.draft.close")}
            </Button>
            <Button type="button" disabled>
              <BanIcon /> {t("skills.detail.draft.publishDisabled")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageScroll>
  );
}

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</span>
      <div className="min-w-0">
        <dt className="text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 break-all font-mono">{value}</dd>
      </div>
    </div>
  );
}
