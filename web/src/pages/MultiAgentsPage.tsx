import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CopyIcon,
  DownloadIcon,
  FileUpIcon,
  LinkIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AgentFeishuPairingDialog } from "@/components/multi-agent/AgentFeishuPairingDialog";
import {
  useCloneMultiAgent,
  useDeleteMultiAgent,
  useImportMultiAgent,
  useMultiAgents,
} from "@/hooks/useMultiAgents";
import { useAgentFeishuConnection } from "@/hooks/useFeishuInstall";
import { isPermissionDenied } from "@/lib/httpErrors";
import { exportAgentBundle, type MultiAgentSummary } from "@/lib/multiAgentApi";
import { Link, useNavigate, useSearchParams } from "@/lib/routing";

type AgentFilter = "all" | "valid" | "issues";

function shortDigest(digest: string): string {
  return digest.replace(/^sha256:/, "").slice(0, 12) || "—";
}

function updatedAt(value: number, language: string): string {
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

function AgentFeishuConnection({
  agent,
  onManage,
}: {
  agent: MultiAgentSummary;
  onManage: () => void;
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const connection = useAgentFeishuConnection(agent.id);
  const connected = connection.data?.status === "connected";
  const identity = connection.data?.bot_name || connection.data?.tenant_name;

  return (
    <div className="flex min-w-40 flex-wrap items-center gap-2">
      {connected ? (
        <span className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
          <span aria-hidden className="size-2 shrink-0 rounded-full bg-emerald-500" />
          <span className="shrink-0">{t("feishu.connected")}</span>
          {identity ? (
            <span className="max-w-28 truncate text-muted-foreground">{identity}</span>
          ) : null}
        </span>
      ) : null}
      <Button size="sm" variant="outline" onClick={onManage} disabled={connection.isLoading}>
        <LinkIcon />
        {connection.isLoading
          ? t("feishu.checkingConnection")
          : connected
            ? t("feishu.changeBinding")
            : t("feishu.connect")}
      </Button>
    </div>
  );
}

export function MultiAgentsPage() {
  const { t, i18n } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const { t: commonT } = useTranslation("common");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const catalog = useMultiAgents();
  const clone = useCloneMultiAgent();
  const remove = useDeleteMultiAgent();
  const importBundle = useImportMultiAgent();
  const fileInput = useRef<HTMLInputElement>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [feishuAgent, setFeishuAgent] = useState<MultiAgentSummary | null>(null);
  const search = params.get("q") ?? "";
  const rawFilter = params.get("status");
  const filter: AgentFilter = rawFilter === "valid" || rawFilter === "issues" ? rawFilter : "all";

  function updateParam(key: string, value: string, defaultValue = "") {
    const next = new URLSearchParams(params);
    if (!value || value === defaultValue) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  }

  const visibleAgents = useMemo(
    () => catalog.data?.filter((agent) => !agent.builtin || agent.worker_count > 0) ?? [],
    [catalog.data],
  );
  const filteredAgents = useMemo(() => {
    const query = search.trim().toLocaleLowerCase(i18n.language);
    return visibleAgents.filter((agent) => {
      if (filter === "valid" && agent.validation_status !== "valid") return false;
      if (filter === "issues" && agent.validation_status === "valid") return false;
      const haystack = [agent.name, agent.description ?? "", agent.harness ?? ""]
        .join(" ")
        .toLocaleLowerCase(i18n.language);
      return !query || haystack.includes(query);
    });
  }, [filter, i18n.language, search, visibleAgents]);

  async function cloneTemplate(agent: MultiAgentSummary) {
    setActionError(null);
    try {
      const draft = await clone.mutateAsync({
        agent_id: agent.id,
        input: { name: `${agent.name}-copy` },
      });
      navigate(`/multi-agents/${draft.card.id}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("errors.action"));
    }
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    setActionError(null);
    try {
      const draft = await importBundle.mutateAsync(file);
      navigate(`/multi-agents/${draft.card.id}`);
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

  async function exportBundle(agent: MultiAgentSummary) {
    setActionError(null);
    try {
      downloadBundle(agent, await exportAgentBundle(agent.id));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : t("errors.action"));
    }
  }

  return (
    <PageScroll contentClassName="px-6" extraBottom="2.5rem" maxWidthClassName="max-w-6xl">
      <CollectionPageHeader
        title={t("title")}
        description={t("catalog.description")}
        actions={
          <>
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
          </>
        }
      />

      <CollectionToolbar className="mt-6">
        <div className="relative min-w-56 flex-1 sm:max-w-sm">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label={t("catalog.search")}
            value={search}
            onChange={(event) => updateParam("q", event.target.value)}
            placeholder={t("catalog.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <SegmentedFilter<AgentFilter>
          label={t("catalog.filterLabel")}
          value={filter}
          onValueChange={(value) => updateParam("status", value, "all")}
          options={[
            { value: "all", label: t("catalog.filters.all"), count: visibleAgents.length },
            {
              value: "valid",
              label: t("catalog.filters.valid"),
              count: visibleAgents.filter((agent) => agent.validation_status === "valid").length,
            },
            {
              value: "issues",
              label: t("catalog.filters.issues"),
              count: visibleAgents.filter((agent) => agent.validation_status !== "valid").length,
            },
          ]}
        />
      </CollectionToolbar>

      {actionError ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-destructive/30 p-3 text-sm text-destructive"
        >
          {actionError}
        </p>
      ) : null}

      <div className="mt-4">
        {catalog.isLoading ? (
          <CollectionState state="loading" title={t("catalog.loading")} />
        ) : catalog.isError ? (
          <CollectionState
            state="error"
            title={
              isPermissionDenied(catalog.error)
                ? commonT("collection.permissionDenied")
                : t("catalog.error")
            }
            description={
              isPermissionDenied(catalog.error)
                ? commonT("collection.permissionDeniedDescription")
                : catalog.error.message
            }
          />
        ) : visibleAgents.length === 0 ? (
          <CollectionState
            state="empty"
            title={t("catalog.emptyTitle")}
            description={t("catalog.emptyDescription")}
          />
        ) : filteredAgents.length === 0 ? (
          <CollectionState state="empty" title={t("catalog.noMatches")} />
        ) : (
          <EntityTable
            caption={t("catalog.tableCaption")}
            columns={[
              { key: "agent", label: t("catalog.columns.agent") },
              { key: "composition", label: t("catalog.columns.composition") },
              { key: "runtime", label: t("catalog.columns.runtime") },
              { key: "version", label: t("catalog.columns.version") },
              { key: "updated", label: t("catalog.columns.updated") },
              { key: "status", label: t("catalog.columns.status") },
              { key: "feishu", label: t("catalog.columns.feishu") },
              {
                key: "actions",
                label: <span className="sr-only">{t("catalog.columns.actions")}</span>,
              },
            ]}
          >
            {filteredAgents.map((agent) => (
              <tr key={agent.id} className="hover:bg-muted/30">
                <td className="max-w-72 px-3 py-3">
                  <h2 className="truncate font-medium">
                    <Link className="hover:underline" to={`/multi-agents/${agent.id}`}>
                      {agent.name}
                    </Link>
                  </h2>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                    {agent.description || t("catalog.noDescription")}
                  </p>
                  {agent.readonly || agent.builtin ? (
                    <StatusBadge className="mt-2" tone="neutral">
                      {t("catalog.builtinReadonly")}
                    </StatusBadge>
                  ) : null}
                </td>
                <td className="px-3 py-3 text-xs text-muted-foreground">
                  <p>{t("metadata.workerCount", { count: agent.worker_count })}</p>
                  <p>{t("metadata.skillCount", { count: agent.skill_count })}</p>
                </td>
                <td className="px-3 py-3 text-muted-foreground">
                  {agent.harness || t("fields.localDefault")}
                </td>
                <td className="px-3 py-3 text-xs">
                  <p>{t("metadata.versionValue", { version: agent.version })}</p>
                  <p className="mt-0.5 font-mono text-muted-foreground" title={agent.digest}>
                    {shortDigest(agent.digest)}
                  </p>
                </td>
                <td className="px-3 py-3 text-muted-foreground">
                  {updatedAt(agent.updated_at, i18n.language)}
                </td>
                <td className="px-3 py-3">
                  <StatusBadge
                    tone={
                      agent.validation_status === "valid"
                        ? "success"
                        : agent.validation_status === "invalid"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {t(`status.${agent.validation_status}`)}
                  </StatusBadge>
                </td>
                <td className="px-3 py-3">
                  <AgentFeishuConnection agent={agent} onManage={() => setFeishuAgent(agent)} />
                </td>
                <td className="px-3 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      size="sm"
                      onClick={() => void cloneTemplate(agent)}
                      disabled={clone.isPending}
                    >
                      <CopyIcon /> {t("actions.useTemplate")}
                    </Button>
                    <EntityRowMenu
                      label={`${agent.name} ${t("catalog.columns.actions")}`}
                      actions={[
                        ...(!agent.readonly && agent.editable !== false
                          ? [
                              {
                                id: "edit",
                                label: t("actions.edit"),
                                icon: <PencilIcon />,
                                onSelect: () => navigate(`/multi-agents/${agent.id}`),
                              },
                            ]
                          : []),
                        {
                          id: "export",
                          label: t("actions.export"),
                          icon: <DownloadIcon />,
                          onSelect: () => void exportBundle(agent),
                        },
                        ...(!agent.readonly && agent.editable !== false
                          ? [
                              {
                                id: "delete",
                                label: t("actions.delete"),
                                icon: <Trash2Icon />,
                                destructive: true,
                                disabled: remove.isPending,
                                onSelect: () => void deleteBundle(agent),
                              },
                            ]
                          : []),
                      ]}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </EntityTable>
        )}
      </div>

      {feishuAgent ? (
        <AgentFeishuPairingDialog
          agentId={feishuAgent.id}
          agentName={feishuAgent.name}
          open
          onOpenChange={(open) => {
            if (!open) setFeishuAgent(null);
          }}
        />
      ) : null}
    </PageScroll>
  );
}
