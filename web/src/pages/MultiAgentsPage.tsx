import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CopyIcon,
  DownloadIcon,
  FileUpIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
  UsersIcon,
} from "lucide-react";
import { PageScroll } from "@/components/PageScroll";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  useCloneMultiAgent,
  useDeleteMultiAgent,
  useImportMultiAgent,
  useMultiAgents,
} from "@/hooks/useMultiAgents";
import { exportAgentBundle, type MultiAgentSummary } from "@/lib/multiAgentApi";
import { Link, useNavigate } from "@/lib/routing";

function shortDigest(digest: string | null | undefined): string {
  return digest?.replace(/^sha256:/, "").slice(0, 12) || "—";
}

function updatedAt(value: number | null, language: string): string {
  if (value == null) return "—";
  const date = new Date(value < 10_000_000_000 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(language).format(date);
}

function downloadBundle(agent: MultiAgentSummary, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${agent.name.replace(/[^a-zA-Z0-9._-]+/g, "-")}.tar.gz`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MultiAgentsPage() {
  const { t, i18n } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const navigate = useNavigate();
  const catalog = useMultiAgents();
  const clone = useCloneMultiAgent();
  const remove = useDeleteMultiAgent();
  const importBundle = useImportMultiAgent();
  const fileInput = useRef<HTMLInputElement>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function cloneTemplate(agent: MultiAgentSummary) {
    setActionError(null);
    try {
      const draft = await clone.mutateAsync({
        agent_id: agent.id,
        input: { name: `${agent.name} copy` },
      });
      navigate(`/multi-agents/${draft.agent.id}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("errors.action"));
    }
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    setActionError(null);
    try {
      const draft = await importBundle.mutateAsync(file);
      navigate(`/multi-agents/${draft.agent.id}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("errors.import"));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function deleteBundle(agent: MultiAgentSummary) {
    if (!window.confirm(t("deleteConfirm", { name: agent.name }))) return;
    setActionError(null);
    try {
      await remove.mutateAsync(agent.id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("errors.action"));
    }
  }

  return (
    <PageScroll contentClassName="px-6 py-8" extraBottom="2.5rem" maxWidthClassName="max-w-5xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Multi-Agent</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("catalog.description")}</p>
        </div>
        <div className="flex gap-2">
          <input
            ref={fileInput}
            className="hidden"
            type="file"
            accept=".tar.gz,.tgz,application/gzip"
            onChange={(event) => void importFile(event.target.files?.[0])}
          />
          <Button
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={importBundle.isPending}
          >
            <FileUpIcon /> {t("actions.import")}
          </Button>
          <Button asChild>
            <Link to="/multi-agents/new">
              <PlusIcon /> {t("actions.create")}
            </Link>
          </Button>
        </div>
      </div>

      {actionError && (
        <p
          role="alert"
          className="mt-5 rounded-lg border border-destructive/30 p-3 text-sm text-destructive"
        >
          {actionError}
        </p>
      )}

      {catalog.isLoading && (
        <div className="flex min-h-52 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Spinner /> {t("catalog.loading")}
        </div>
      )}
      {catalog.isError && (
        <div
          role="alert"
          className="mt-6 rounded-xl border border-destructive/30 p-6 text-sm text-destructive"
        >
          {t("catalog.error")}: {catalog.error.message}
        </div>
      )}
      {!catalog.isLoading && !catalog.isError && catalog.data?.length === 0 && (
        <Card className="mt-6 border-dashed text-center shadow-none">
          <CardContent className="py-10">
            <UsersIcon className="mx-auto mb-3 size-8 text-muted-foreground" />
            <p className="font-medium">{t("catalog.emptyTitle")}</p>
            <p className="mt-1 text-sm text-muted-foreground">{t("catalog.emptyDescription")}</p>
          </CardContent>
        </Card>
      )}
      {!!catalog.data?.length && (
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {catalog.data.map((agent) => (
            <Card key={agent.id}>
              <CardHeader>
                <CardTitle>
                  <h2>{agent.name}</h2>
                </CardTitle>
                <CardDescription>{agent.description || t("catalog.noDescription")}</CardDescription>
                <CardAction>
                  <Badge
                    variant={agent.validation_status === "invalid" ? "destructive" : "outline"}
                  >
                    {t(`status.${agent.validation_status}`)}
                  </Badge>
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                {agent.builtin && <Badge variant="secondary">{t("catalog.builtinReadonly")}</Badge>}
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs sm:grid-cols-3">
                  <div>
                    <dt className="text-muted-foreground">{t("metadata.workers")}</dt>
                    <dd className="mt-0.5 font-medium">
                      {t("metadata.workerCount", { count: agent.worker_count })}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("metadata.version")}</dt>
                    <dd className="mt-0.5 font-medium">
                      {t("metadata.versionValue", { version: agent.version })}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("metadata.digest")}</dt>
                    <dd className="mt-0.5 font-mono" title={agent.digest ?? undefined}>
                      {shortDigest(agent.digest)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("fields.harness")}</dt>
                    <dd className="mt-0.5 font-medium">
                      {agent.harness || t("fields.localDefault")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("metadata.updated")}</dt>
                    <dd className="mt-0.5 font-medium">
                      {updatedAt(agent.updated_at, i18n.language)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
              <CardFooter className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  onClick={() => void cloneTemplate(agent)}
                  disabled={clone.isPending}
                >
                  <CopyIcon /> {t("actions.useTemplate")}
                </Button>
                {agent.editable && (
                  <Button asChild size="sm" variant="outline">
                    <Link to={`/multi-agents/${agent.id}`}>
                      <PencilIcon /> {t("actions.edit")}
                    </Link>
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void exportAgentBundle(agent.id)
                      .then((blob) => downloadBundle(agent, blob))
                      .catch((error: unknown) =>
                        setActionError(error instanceof Error ? error.message : t("errors.action")),
                      )
                  }
                >
                  <DownloadIcon /> {t("actions.export")}
                </Button>
                {agent.editable && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void deleteBundle(agent)}
                    disabled={remove.isPending}
                  >
                    <Trash2Icon /> {t("actions.delete")}
                  </Button>
                )}
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </PageScroll>
  );
}
