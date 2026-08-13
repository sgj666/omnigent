import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ActivityIcon,
  BotIcon,
  FolderIcon,
  LinkIcon,
  PlusIcon,
  SaveIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react";
import { AgentConfigEditor } from "@/components/multi-agent/AgentConfigEditor";
import { AgentFeishuPairingDialog } from "@/components/multi-agent/AgentFeishuPairingDialog";
import { BundleDiagnostics } from "@/components/multi-agent/BundleDiagnostics";
import { PageBackButton } from "@/components/PageBackButton";
import { PageScroll } from "@/components/PageScroll";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  useAgentBundleOptions,
  useAgentActivity,
  useAgentFormSchema,
  useCreateMultiAgent,
  useMultiAgent,
  useUpdateMultiAgent,
} from "@/hooks/useMultiAgents";
import { useAgentDefaultWorkspaceScope, useAgentFeishuConnection } from "@/hooks/useFeishuInstall";
import { useHostModelOptions, useHostSkillOptions, useHosts } from "@/hooks/useHosts";
import {
  buildConfigPatches,
  DraftJsonError,
  parseAgentYaml,
  readAgentConfig,
  resolvePromptFile,
  workerName,
  type AgentConfigDraft,
  type PromptReference,
} from "@/lib/multiAgentDraft";
import {
  AgentBundleApiError,
  AgentVersionConflict,
  type AgentBundleFile,
  type AgentActivityRun,
  type AgentBundlePatch,
  type AgentBundleValue,
  type AgentFormSchema,
  type BundleDiagnostic,
  type DeliveryWorkflowConfig,
  type WorkerOperation,
} from "@/lib/multiAgentApi";
import { Link, useNavigate, useParams } from "@/lib/routing";

function activityTimestamp(value: number | null, language: string): string {
  if (value === null) return "—";
  return new Intl.DateTimeFormat(language, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value * 1000));
}

function bundledSkillNames(configPath: string, files: AgentBundleFile[]): string[] {
  const scope = configPath.split("/").slice(0, -1).join("/");
  const prefix = scope ? `${scope}/skills/` : "skills/";
  return files
    .map((file) => file.path)
    .filter((path) => path.startsWith(prefix) && path.endsWith("/SKILL.md"))
    .map((path) => path.slice(prefix.length, -"/SKILL.md".length))
    .filter((name) => name.length > 0 && !name.includes("/"))
    .sort();
}

function deliveryWorkflow(file: AgentBundleFile | null): DeliveryWorkflowConfig | null {
  const data = file?.data;
  if (data === null || typeof data !== "object" || Array.isArray(data)) return null;
  const value = data.delivery_workflow;
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  if (value.profile !== "zhuanspec-development" || value.role !== "coordinator") return null;
  return { profile: value.profile, role: value.role };
}

function AgentActivityPanel({ agentId }: { agentId: string }) {
  const { t, i18n } = useTranslation("agents", { keyPrefix: "multiAgent.activity" });
  const activity = useAgentActivity(agentId);

  if (activity.isLoading) {
    return (
      <Card data-testid="agent-activity">
        <CardContent className="py-8 text-sm text-muted-foreground">{t("loading")}</CardContent>
      </Card>
    );
  }

  if (activity.isError || !activity.data) {
    return (
      <Card data-testid="agent-activity">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-6">
          <p role="alert" className="text-sm text-destructive">
            {t("error")}
          </p>
          <Button variant="outline" size="sm" onClick={() => void activity.refetch()}>
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const data = activity.data;
  const metrics = [
    ["totalRuns", data.total_runs],
    ["activeRuns", data.active_runs],
    [
      "successRate",
      data.success_rate === null
        ? t("noTerminalSample")
        : new Intl.NumberFormat(i18n.language, {
            style: "percent",
            maximumFractionDigits: 1,
          }).format(data.success_rate),
    ],
    ["waitingRuns", data.waiting_runs],
    ["failedRuns", data.failed_runs],
  ] as const;

  function stateBadge(run: AgentActivityRun) {
    return (
      <Badge
        variant={run.state === "failed" ? "destructive" : "outline"}
        className={
          run.state === "succeeded"
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
            : run.state === "running"
              ? "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-400"
              : run.state === "waiting"
                ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                : undefined
        }
      >
        {t(`states.${run.state}`, { defaultValue: run.state })}
      </Badge>
    );
  }

  return (
    <Card data-testid="agent-activity">
      <CardHeader>
        <div className="flex items-center gap-2">
          <ActivityIcon className="size-4 text-muted-foreground" />
          <CardTitle>{t("title")}</CardTitle>
        </div>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {metrics.map(([key, value]) => (
            <div key={key} className="rounded-xl border bg-muted/20 p-3">
              <p className="text-xs text-muted-foreground">{t(`metrics.${key}`)}</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
            </div>
          ))}
        </div>

        <div>
          <h2 className="text-sm font-semibold">{t("recentRuns")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t("recentRunsDescription")}</p>
          {data.recent_runs.length === 0 ? (
            <p className="mt-3 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {t("emptyRuns")}
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t("columns.taskRun")}</th>
                    <th className="px-3 py-2 font-medium">{t("columns.state")}</th>
                    <th className="px-3 py-2 font-medium">{t("columns.project")}</th>
                    <th className="px-3 py-2 font-medium">{t("columns.reason")}</th>
                    <th className="px-3 py-2 font-medium">{t("columns.queuedAt")}</th>
                    <th className="px-3 py-2 font-medium">{t("columns.session")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.recent_runs.map((run) => (
                    <tr key={run.id} className="align-top hover:bg-muted/20">
                      <td className="max-w-64 px-3 py-3">
                        <Link
                          to={`/tasks/${run.task_id}#run-${run.id}`}
                          className="font-medium hover:underline"
                        >
                          {run.task_title}
                        </Link>
                        <p
                          className="mt-1 font-mono text-[11px] text-muted-foreground"
                          title={run.id}
                        >
                          {t("runId", { id: run.id.slice(0, 8) })}
                        </p>
                      </td>
                      <td className="px-3 py-3">{stateBadge(run)}</td>
                      <td className="max-w-48 px-3 py-3">
                        {run.project_id && run.project_name ? (
                          <Link to={`/projects/${run.project_id}`} className="hover:underline">
                            {run.project_name}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="max-w-72 px-3 py-3 text-xs text-muted-foreground">
                        {run.waiting_reason || run.failure_message || run.failure_code || "—"}
                        {run.failure_code && run.failure_message && (
                          <p className="mt-1 font-mono text-[11px]">{run.failure_code}</p>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-xs text-muted-foreground">
                        {activityTimestamp(run.queued_at, i18n.language)}
                      </td>
                      <td className="px-3 py-3">
                        {run.session_id ? (
                          <Link
                            to={`/c/${run.session_id}`}
                            className="font-mono text-xs hover:underline"
                            title={run.session_id}
                          >
                            {t("sessionId", { id: run.session_id.slice(0, 8) })}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border p-4">
            <div className="flex items-center gap-2">
              <FolderIcon className="size-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold">{t("projects")}</h2>
            </div>
            {data.projects.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">{t("emptyProjects")}</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {data.projects.map((project) => (
                  <li key={project.id} className="flex items-center justify-between gap-3 text-sm">
                    <Link to={`/projects/${project.id}`} className="truncate hover:underline">
                      {project.name}
                    </Link>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {t("runCount", { count: project.run_count })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="rounded-xl border p-4">
            <div className="flex items-center gap-2">
              <WrenchIcon className="size-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold">{t("skills")}</h2>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("skillsDescription")}</p>
            {data.skills.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">{t("emptySkills")}</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {data.skills.map((skill) => (
                  <li key={skill.name} className="flex items-center justify-between gap-3 text-sm">
                    <span className="truncate font-mono text-xs">{skill.name}</span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {t("useCount", { count: skill.uses })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface EditableFile {
  path: string;
  name: string;
  original: AgentBundleValue;
  visual: AgentConfigDraft;
  yaml: string;
  yamlDirty: boolean;
  visualDirty: boolean;
  pending: boolean;
  promptReference: PromptReference | null;
  yamlDiagnostic: BundleDiagnostic | null;
}

interface RawTextFile {
  path: string;
  yaml: string | null;
  original: string | null;
  inline: boolean;
  size: number;
}

interface PendingOrderPatch {
  agentId: string;
  expectedVersion: number;
  patches: AgentBundlePatch[];
}

interface PendingOrderConflict {
  serverVersion: number | null;
}

interface PendingWorkerDelete {
  name: string;
  references: string[];
}

function editableFile(
  file: AgentBundleFile,
  pending = false,
  files: AgentBundleFile[] = [],
  schema?: AgentFormSchema,
): EditableFile | null {
  if (file.data === undefined || file.content == null) return null;
  const promptReference = resolvePromptFile(file.path, file.data, files);
  return {
    path: file.path,
    name: workerName(file.path, file.data),
    original: file.data,
    visual: readAgentConfig(file.data, promptReference?.content, schema),
    yaml: file.content,
    yamlDirty: false,
    visualDirty: false,
    pending,
    promptReference,
    yamlDiagnostic: null,
  };
}

function workerOrderPatch(
  coordinator: EditableFile,
  workers: EditableFile[],
): AgentBundlePatch | null {
  const root = coordinator.original;
  if (root === null || typeof root !== "object" || Array.isArray(root)) return null;
  const tools = root.tools;
  if (tools === null || typeof tools !== "object" || Array.isArray(tools)) return null;
  const original = tools.agents;
  if (!Array.isArray(original)) return null;
  const next = workers.map((worker) => worker.name);
  if (JSON.stringify(original) === JSON.stringify(next)) return null;
  return {
    file: coordinator.path,
    op: "replace",
    path: "/tools/agents",
    value: next,
  };
}

function draftWorkerName(worker: EditableFile): string {
  return worker.pending ? worker.visual.name.trim() || worker.name : worker.name;
}

function modelPreviewHarness(harness: string): string | null {
  if (["claude", "claude_sdk", "claude-sdk", "claude-native"].includes(harness))
    return "claude-native";
  if (["codex", "codex-native"].includes(harness)) return "codex-native";
  return null;
}

function CreateBundleForm() {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const create = useCreateMultiAgent();
  const options = useAgentBundleOptions(true);
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [harness, setHarness] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !harness) return;
    const draft = await create.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
      config: {
        spec_version: 1,
        name: name.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        executor: { type: "omnigent", config: { harness } },
      },
    });
    navigate(`/multi-agents/${draft.card.id}`);
  }

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>
          <h1>{t("editor.newTitle")}</h1>
        </CardTitle>
        <CardDescription>{t("editor.createHelp")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <div className="space-y-1.5">
            <label htmlFor="bundle-name" className="text-xs font-medium text-muted-foreground">
              {t("fields.name")}
            </label>
            <Input
              id="bundle-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              {t("fields.harness")}
            </label>
            <Select value={harness} onValueChange={setHarness}>
              <SelectTrigger aria-label={t("fields.harness")} className="w-full">
                <SelectValue placeholder={t("fields.harness")} />
              </SelectTrigger>
              <SelectContent>
                {(options.data?.harnesses ?? []).map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="bundle-description"
              className="text-xs font-medium text-muted-foreground"
            >
              {t("fields.description")}
            </label>
            <Input
              id="bundle-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={!name.trim() || !harness || create.isPending}>
            <PlusIcon /> {create.isPending ? t("actions.saving") : t("actions.create")}
          </Button>
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
              {create.error.message}
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

export function MultiAgentDetailPage() {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const { agentId } = useParams<{ agentId: string }>();
  const isNew = agentId == null || agentId === "new";
  const bundle = useMultiAgent(isNew ? null : agentId);
  const formSchema = useAgentFormSchema(!isNew);
  const bundleOptions = useAgentBundleOptions(!isNew);
  const hosts = useHosts({ enabled: !isNew });
  const feishuConnection = useAgentFeishuConnection(agentId ?? "", !isNew && Boolean(agentId));
  const defaultWorkspace = useAgentDefaultWorkspaceScope(agentId ?? "", !isNew && Boolean(agentId));
  const update = useUpdateMultiAgent();
  const [mode, setMode] = useState("visual");
  const [coordinator, setCoordinator] = useState<EditableFile | null>(null);
  const [workers, setWorkers] = useState<EditableFile[]>([]);
  const [rawFiles, setRawFiles] = useState<RawTextFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>("config.yaml");
  const [workerOperations, setWorkerOperations] = useState<WorkerOperation[]>([]);
  const [pendingOrderPatch, setPendingOrderPatch] = useState<PendingOrderPatch | null>(null);
  const pendingOrderPatchRef = useRef<PendingOrderPatch | null>(null);
  const [pendingOrderConflict, setPendingOrderConflict] = useState<PendingOrderConflict | null>(
    null,
  );
  const [diagnostics, setDiagnostics] = useState<BundleDiagnostic[]>([]);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pendingWorkerDelete, setPendingWorkerDelete] = useState<PendingWorkerDelete | null>(null);
  const [initializedVersion, setInitializedVersion] = useState<string | null>(null);
  const [feishuOpen, setFeishuOpen] = useState(false);

  function rememberPendingOrderPatch(pending: PendingOrderPatch) {
    pendingOrderPatchRef.current = pending;
    setPendingOrderPatch(pending);
    setPendingOrderConflict(null);
  }

  function clearPendingOrderPatch() {
    pendingOrderPatchRef.current = null;
    setPendingOrderPatch(null);
  }

  function reloadAfterOrderConflict() {
    clearPendingOrderPatch();
    setPendingOrderConflict(null);
    setSaveError(null);
    setSaveMessage(null);
    setWorkerOperations([]);
    setInitializedVersion(null);
    void bundle.refetch();
  }

  useEffect(() => {
    if (!bundle.data) return;
    const pending = pendingOrderPatchRef.current;
    if (pending?.agentId === bundle.data.card.id) return;
    if (pending) clearPendingOrderPatch();
    const key = `${bundle.data.card.id}:${bundle.data.version}:${formSchema.data?.schema_version ?? ""}`;
    if (key === initializedVersion) return;
    setInitializedVersion(key);
    const configPaths = new Set([
      bundle.data.coordinator?.path,
      ...bundle.data.workers.map((file) => file.path),
    ]);
    setCoordinator(
      bundle.data.coordinator
        ? editableFile(bundle.data.coordinator, false, bundle.data.files, formSchema.data)
        : null,
    );
    setWorkers(
      bundle.data.workers
        .map((file) => editableFile(file, false, bundle.data.files, formSchema.data))
        .filter((file): file is EditableFile => file !== null),
    );
    setRawFiles(
      bundle.data.files
        .filter((file) => !configPaths.has(file.path))
        .map((file) => ({
          path: file.path,
          yaml: file.content,
          original: file.content,
          inline: file.inline !== false && file.content !== null,
          size: file.size ?? 0,
        })),
    );
    setSelectedPath(bundle.data.coordinator?.path ?? bundle.data.workers[0]?.path ?? "config.yaml");
    setDiagnostics(bundle.data.diagnostics);
    setWorkerOperations([]);
    setPendingWorkerDelete(null);
  }, [bundle.data, formSchema.data, initializedVersion, pendingOrderPatch]);

  const allFiles = useMemo(
    () => [coordinator, ...workers].filter((file): file is EditableFile => file !== null),
    [coordinator, workers],
  );
  const visualDirtyTargets = useMemo(() => {
    const targets = new Set<string>();
    for (const file of allFiles) {
      if (!file.visualDirty) continue;
      targets.add(file.path);
      if (file.promptReference) targets.add(file.promptReference.path);
    }
    return targets;
  }, [allFiles]);
  const selectedRaw = rawFiles.find((file) => file.path === selectedPath);
  const selected =
    allFiles.find((file) => file.path === selectedPath) ??
    (selectedRaw ? undefined : (coordinator ?? workers[0]));
  const previewHost =
    hosts.data?.find(
      (host) => host.status === "online" && host.host_id === defaultWorkspace.data?.host_id,
    ) ??
    hosts.data?.find((host) => host.status === "online") ??
    null;
  const previewHostId = previewHost?.host_id ?? null;
  const previewHarness = modelPreviewHarness(selected?.visual.harness ?? "");
  const configuredDeliveryWorkflow = deliveryWorkflow(bundle.data?.coordinator ?? null);
  const hostModels = useHostModelOptions(
    previewHostId,
    previewHarness ?? "",
    !isNew && previewHarness !== null,
  );
  const hostSkills = useHostSkillOptions(
    previewHostId,
    previewHarness ?? "",
    defaultWorkspace.data?.workspace,
    !isNew && previewHarness !== null,
  );
  const modelOptions = useMemo(() => {
    const hosted = (hostModels.data ?? []).map((model) => ({
      id: model.model || model.id,
      label: model.displayName || model.id,
    }));
    if (hosted.length > 0) return hosted;
    const advertised: { id: string; label: string }[] = [];
    for (const model of bundleOptions.data?.models ?? []) {
      const modelHarness = typeof model.harness === "string" ? model.harness : null;
      if (modelHarness && modelHarness !== selected?.visual.harness) continue;
      const id =
        typeof model.model === "string"
          ? model.model
          : typeof model.id === "string"
            ? model.id
            : null;
      if (!id) continue;
      const label =
        typeof model.label === "string"
          ? model.label
          : typeof model.displayName === "string"
            ? model.displayName
            : id;
      advertised.push({ id, label });
    }
    return advertised;
  }, [bundleOptions.data?.models, hostModels.data, selected?.visual.harness]);
  const readonly = bundle.data?.card.readonly === true || bundle.data?.card.editable === false;
  const hasInvalidYaml = allFiles.some((file) => file.yamlDiagnostic !== null);
  const feishuStatus = feishuConnection.data?.status ?? "disconnected";
  const feishuConnected = feishuStatus === "connected";
  const feishuIdentity = feishuConnection.data?.bot_name || feishuConnection.data?.tenant_name;

  function updateSelected(transform: (file: EditableFile) => EditableFile) {
    if (!selected) return;
    if (coordinator?.path === selected.path) setCoordinator(transform(coordinator));
    else
      setWorkers((items) =>
        items.map((item) => (item.path === selected.path ? transform(item) : item)),
      );
  }

  function updateSelectedYaml(source: string) {
    if (!selected) return;
    if (selected.visualDirty) return;
    const parsed = parseAgentYaml(source);
    if (parsed.diagnostic !== null) {
      updateSelected((file) => ({
        ...file,
        yaml: source,
        yamlDirty: true,
        yamlDiagnostic: {
          severity: "error",
          code: "invalid_yaml",
          file: file.path,
          path: null,
          line: parsed.diagnostic.line,
          column: parsed.diagnostic.column,
          message: parsed.diagnostic.message,
        },
      }));
      return;
    }

    const files = [
      ...allFiles.map((file) => ({ path: file.path, content: file.yaml })),
      ...rawFiles.map((file) => ({ path: file.path, content: file.yaml })),
    ];
    const promptReference = resolvePromptFile(selected.path, parsed.data, files);
    updateSelected((file) => ({
      ...file,
      original: parsed.data,
      visual: readAgentConfig(parsed.data, promptReference?.content, formSchema.data),
      yaml: source,
      yamlDirty: true,
      visualDirty: false,
      promptReference,
      yamlDiagnostic: null,
    }));
  }

  function updateSelectedRaw(source: string) {
    if (!selectedRaw || visualDirtyTargets.has(selectedRaw.path)) return;
    setRawFiles((files) =>
      files.map((file) => (file.path === selectedRaw.path ? { ...file, yaml: source } : file)),
    );
  }

  function addWorker() {
    let number = workers.length + 1;
    let name = t("workers.newName", { number });
    while (workers.some((worker) => worker.name === name)) {
      number += 1;
      name = t("workers.newName", { number });
    }
    const path = `agents/${name}/config.yaml`;
    const original: AgentBundleValue = { name };
    const pending: EditableFile = {
      path,
      name,
      original,
      visual: readAgentConfig(original, undefined, formSchema.data),
      yaml: `name: ${name}\n`,
      yamlDirty: false,
      visualDirty: false,
      pending: true,
      promptReference: null,
      yamlDiagnostic: null,
    };
    setWorkers((items) => [...items, pending]);
    setWorkerOperations((items) => [...items, { op: "add", name, source: "minimal" }]);
    setSelectedPath(path);
  }

  function removeWorker(index: number) {
    const worker = workers[index];
    setWorkers((items) => items.filter((_, itemIndex) => itemIndex !== index));
    if (worker.pending) {
      setWorkerOperations((items) =>
        items.filter((operation) => !(operation.op === "add" && operation.name === worker.name)),
      );
    } else {
      setWorkerOperations((items) => [...items, { op: "delete", name: worker.name }]);
    }
    if (selectedPath === worker.path) setSelectedPath(coordinator?.path ?? "config.yaml");
  }

  function moveWorker(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= workers.length) return;
    setWorkers((items) => {
      const next = [...items];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function save(confirmedDelete?: PendingWorkerDelete) {
    if (!agentId || !bundle.data || !coordinator || readonly || pendingOrderConflict) return;
    setSaveMessage(null);
    setSaveError(null);
    try {
      const pendingOrder = pendingOrderPatchRef.current;
      if (pendingOrder?.agentId === agentId) {
        const saved = await update.mutateAsync({
          agent_id: agentId,
          request: {
            expected_version: pendingOrder.expectedVersion,
            patches: pendingOrder.patches,
          },
        });
        setDiagnostics(saved.diagnostics);
        setInitializedVersion(`${bundle.data.card.id}:${bundle.data.version}`);
        clearPendingOrderPatch();
        setSaveMessage(t("editor.saved"));
        return;
      }
      const invalidYaml = allFiles.find((file) => file.yamlDiagnostic !== null)?.yamlDiagnostic;
      if (invalidYaml) {
        setDiagnostics([invalidYaml]);
        setSaveError(
          t("editor.invalidYaml", { line: invalidYaml.line, column: invalidYaml.column }),
        );
        return;
      }
      const patches = allFiles.flatMap((file) => {
        if (file.pending) return [];
        return [
          ...(file.yamlDirty
            ? [{ file: file.path, op: "replace_file" as const, value: file.yaml }]
            : []),
          ...buildConfigPatches(file.path, file.original, file.visual, {
            reference: file.promptReference,
          }),
        ];
      });
      for (const file of rawFiles) {
        if (file.yaml === null || file.original === null) continue;
        if (visualDirtyTargets.has(file.path)) continue;
        if (file.yaml !== file.original) {
          patches.push({ file: file.path, op: "replace_file", value: file.yaml });
        }
      }
      const requestedOperations = confirmedDelete
        ? workerOperations.map((operation) =>
            operation.op === "delete" && operation.name === confirmedDelete.name
              ? { ...operation, confirmed_references: confirmedDelete.references }
              : operation,
          )
        : workerOperations;
      const operations = requestedOperations.map((operation) => {
        if (operation.op !== "add") return operation;
        const pendingWorker = workers.find(
          (worker) => worker.pending && worker.name === operation.name,
        );
        return pendingWorker ? { ...operation, name: draftWorkerName(pendingWorker) } : operation;
      });
      if (confirmedDelete) setWorkerOperations(operations);
      const requiresPostOperationOrder = operations.length > 0;
      const order = requiresPostOperationOrder
        ? null
        : workerOrderPatch(
            coordinator,
            workers.filter((worker) => !worker.pending),
          );
      if (order) patches.push(order);
      let saved = await update.mutateAsync({
        agent_id: agentId,
        request: {
          expected_version: bundle.data.version,
          ...(patches.length ? { patches } : {}),
          ...(operations.length ? { worker_operations: operations } : {}),
        },
      });
      if (requiresPostOperationOrder) {
        setWorkerOperations([]);
        const desiredOrder = workers.map(draftWorkerName);
        const savedOrder = saved.workers.map((worker) => workerName(worker.path, worker.data));
        const postOperationPatches: AgentBundlePatch[] = [];
        for (const pendingWorker of workers.filter((worker) => worker.pending)) {
          const name = draftWorkerName(pendingWorker);
          const savedWorker = saved.workers.find(
            (worker) => workerName(worker.path, worker.data) === name,
          );
          if (!savedWorker?.data) continue;
          const savedVisual = readAgentConfig(savedWorker.data, undefined, formSchema.data);
          postOperationPatches.push(
            ...buildConfigPatches(savedWorker.path, savedWorker.data, {
              ...pendingWorker.visual,
              name,
              // A minimal worker inherits the coordinator executor on the
              // server. Keep those materialized defaults when the user left
              // the worker selectors on "Use local default".
              harness: pendingWorker.visual.harness || savedVisual.harness,
              model: pendingWorker.visual.model || savedVisual.model,
            }),
          );
        }
        if (JSON.stringify(savedOrder) !== JSON.stringify(desiredOrder)) {
          postOperationPatches.push({
            file: saved.coordinator?.path ?? coordinator.path,
            op: "replace",
            path: "/tools/agents",
            value: desiredOrder,
          });
        }
        if (postOperationPatches.length > 0) {
          const nextOrderPatch: PendingOrderPatch = {
            agentId,
            expectedVersion: saved.version,
            patches: postOperationPatches,
          };
          rememberPendingOrderPatch(nextOrderPatch);
          saved = await update.mutateAsync({
            agent_id: agentId,
            request: {
              expected_version: nextOrderPatch.expectedVersion,
              patches: nextOrderPatch.patches,
            },
          });
          setInitializedVersion(`${bundle.data.card.id}:${bundle.data.version}`);
          clearPendingOrderPatch();
        }
      }
      setDiagnostics(saved.diagnostics);
      setWorkerOperations([]);
      setPendingWorkerDelete(null);
      setSaveMessage(t("editor.saved"));
    } catch (error) {
      if (error instanceof DraftJsonError) {
        setSaveError(t("errors.invalidJson", { field: t(`fields.${error.field}`) }));
      } else {
        if (error instanceof AgentBundleApiError) {
          setDiagnostics(error.diagnostics);
          const confirmationDiagnostics = error.diagnostics.filter(
            (diagnostic) => diagnostic.code === "worker_references_require_confirmation",
          );
          const referencedWorker = confirmationDiagnostics[0]?.worker;
          const references = confirmationDiagnostics.filter(
            (diagnostic) => diagnostic.worker === referencedWorker,
          );
          const pendingDelete = workerOperations.find(
            (operation): operation is Extract<WorkerOperation, { op: "delete" }> =>
              operation.op === "delete" && operation.name === referencedWorker,
          );
          if (pendingDelete && references.length) {
            setPendingWorkerDelete({
              name: pendingDelete.name,
              references: references.map(
                (diagnostic) => `${diagnostic.file ?? ""}#${diagnostic.path ?? ""}`,
              ),
            });
          }
        }
        if (
          error instanceof AgentVersionConflict &&
          error.code === "version_conflict" &&
          pendingOrderPatchRef.current
        ) {
          setPendingOrderConflict({ serverVersion: error.server_version });
          setSaveError(null);
        } else {
          setSaveError(error instanceof Error ? error.message : t("errors.action"));
        }
      }
    }
  }

  if (!isNew && bundle.isLoading)
    return (
      <div className="flex min-h-full items-center justify-center text-sm text-muted-foreground">
        {t("editor.loading")}
      </div>
    );
  if (!isNew && (bundle.isError || !bundle.data))
    return (
      <div role="alert" className="p-8 text-sm text-destructive">
        {t("editor.loadError")}
        {bundle.error ? `: ${bundle.error.message}` : ""}
      </div>
    );

  return (
    <PageScroll contentClassName="px-6 py-8" extraBottom="2.5rem" maxWidthClassName="max-w-6xl">
      <PageBackButton fallbackTo="/multi-agents" className="-ml-3 mb-4">
        {t("actions.back")}
      </PageBackButton>
      {isNew ? (
        <CreateBundleForm />
      ) : (
        bundle.data && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold">{bundle.data.card.name}</h1>
                  {(bundle.data.card.readonly || bundle.data.card.builtin) && (
                    <Badge variant="secondary">{t("catalog.builtinReadonly")}</Badge>
                  )}
                  <Badge
                    variant={
                      bundle.data.card.validation_status === "invalid" ? "destructive" : "outline"
                    }
                  >
                    {t(`status.${bundle.data.card.validation_status}`)}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{bundle.data.card.description}</p>
                <p className="mt-2 font-mono text-xs text-muted-foreground">
                  v{bundle.data.version} · {bundle.data.digest}
                </p>
                {configuredDeliveryWorkflow && (
                  <div
                    data-testid="delivery-workflow"
                    className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
                  >
                    <span>{t("deliveryWorkflow.label")}</span>
                    <Badge variant="outline">
                      {t(`deliveryWorkflow.profiles.${configuredDeliveryWorkflow.profile}`)}
                    </Badge>
                    <Badge variant="secondary">
                      {t(`deliveryWorkflow.roles.${configuredDeliveryWorkflow.role}`)}
                    </Badge>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant={feishuStatus === "error" ? "destructive" : "outline"}
                  className={
                    feishuConnected
                      ? "gap-1.5 border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : undefined
                  }
                >
                  {feishuConnected && (
                    <span aria-hidden className="size-2 rounded-full bg-emerald-500" />
                  )}
                  {feishuConnection.isLoading
                    ? t("feishu.checkingConnection")
                    : feishuConnected
                      ? t("feishu.connected")
                      : t(`status.${feishuStatus}`, { defaultValue: feishuStatus })}
                  {feishuConnected && feishuIdentity && ` · ${feishuIdentity}`}
                </Badge>
                <Button
                  variant="outline"
                  onClick={() => setFeishuOpen(true)}
                  disabled={feishuConnection.isLoading}
                >
                  <LinkIcon />
                  {feishuConnected ? t("feishu.changeBinding") : t("feishu.connect")}
                </Button>
                {!readonly && (
                  <Button
                    onClick={() => void save()}
                    disabled={update.isPending || hasInvalidYaml || pendingOrderConflict !== null}
                  >
                    <SaveIcon />
                    {update.isPending ? t("actions.saving") : t("actions.save")}
                  </Button>
                )}
              </div>
            </div>

            {readonly && (
              <Card className="border-dashed shadow-none">
                <CardContent className="py-3 text-sm text-muted-foreground">
                  {t("editor.readonly")}
                </CardContent>
              </Card>
            )}
            <BundleDiagnostics diagnostics={diagnostics} />
            {saveMessage && (
              <p role="status" className="text-sm text-primary">
                {saveMessage}
              </p>
            )}
            {saveError && (
              <p role="alert" className="text-sm text-destructive">
                {saveError}
              </p>
            )}
            {pendingOrderConflict && (
              <div role="alert" className="space-y-2 text-sm text-destructive">
                <p>
                  {t("editor.orderVersionConflict", {
                    version: pendingOrderConflict.serverVersion ?? "?",
                  })}
                </p>
                <Button variant="outline" size="sm" onClick={reloadAfterOrderConflict}>
                  {t("actions.reloadServerVersion")}
                </Button>
              </div>
            )}
            {pendingWorkerDelete && (
              <div role="alert" className="space-y-2 rounded-md border p-3 text-sm">
                <p>{t("workers.referenceConfirmation", { name: pendingWorkerDelete.name })}</p>
                <ul className="list-disc pl-5 font-mono text-xs">
                  {pendingWorkerDelete.references.map((reference) => (
                    <li key={reference}>{reference}</li>
                  ))}
                </ul>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => void save(pendingWorkerDelete)}
                  disabled={update.isPending}
                >
                  {t("workers.confirmDelete")}
                </Button>
              </div>
            )}

            <AgentActivityPanel agentId={bundle.data.card.id} />

            <div className="grid items-start gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
              <Card className="self-start lg:sticky lg:top-6">
                <CardHeader className="border-b">
                  <CardTitle>{t("editor.teamMembers")}</CardTitle>
                  <CardDescription>{t("editor.teamMembersHelp")}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4 p-3">
                  {coordinator && (
                    <div className="space-y-1">
                      <span className="px-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                        {t("editor.coordinator")}
                      </span>
                      <Button
                        className="h-auto w-full justify-start gap-3 px-3 py-2.5 text-left"
                        variant={selected?.path === coordinator.path ? "secondary" : "ghost"}
                        aria-label={
                          coordinator.visual.name || coordinator.name || t("editor.coordinator")
                        }
                        onClick={() => setSelectedPath(coordinator.path)}
                      >
                        <BotIcon className="size-4 shrink-0" />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">
                            {coordinator.visual.name || coordinator.name || t("editor.coordinator")}
                          </span>
                          <span className="block truncate text-[11px] font-normal text-muted-foreground">
                            {coordinator.visual.harness || t("fields.localDefault")}
                            {coordinator.visual.model ? ` · ${coordinator.visual.model}` : ""}
                          </span>
                        </span>
                      </Button>
                    </div>
                  )}
                  <div className="space-y-2 border-t pt-4">
                    <div className="flex items-center justify-between px-2">
                      <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                        {t("editor.workers")}
                      </span>
                      {!readonly && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          aria-label={t("actions.addWorker")}
                          onClick={addWorker}
                        >
                          <PlusIcon />
                          {t("actions.addWorker")}
                        </Button>
                      )}
                    </div>
                    {workers.length === 0 && (
                      <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                        {t("workers.empty")}
                      </p>
                    )}
                    {workers.map((worker, index) => {
                      const displayName = draftWorkerName(worker);
                      return (
                        <div key={worker.path} className="flex items-center gap-1">
                          <Button
                            className="h-auto min-w-0 flex-1 justify-start px-3 py-2.5 text-left"
                            variant={selected?.path === worker.path ? "secondary" : "ghost"}
                            aria-label={displayName}
                            onClick={() => setSelectedPath(worker.path)}
                          >
                            <span className="min-w-0">
                              <span className="flex items-center gap-1.5">
                                <span className="truncate font-medium">{displayName}</span>
                                {worker.pending && (
                                  <Badge variant="outline" className="h-4 px-1.5 text-[10px]">
                                    {t("status.pending")}
                                  </Badge>
                                )}
                              </span>
                              <span className="block truncate text-[11px] font-normal text-muted-foreground">
                                {worker.visual.harness || t("fields.localDefault")}
                                {worker.visual.model ? ` · ${worker.visual.model}` : ""}
                              </span>
                            </span>
                          </Button>
                          {!readonly && (
                            <div className="flex shrink-0 flex-col">
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label={`${t("actions.moveUp")} ${worker.name}`}
                                disabled={index === 0}
                                onClick={() => moveWorker(index, -1)}
                              >
                                <ArrowUpIcon />
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label={`${t("actions.moveDown")} ${worker.name}`}
                                disabled={index === workers.length - 1}
                                onClick={() => moveWorker(index, 1)}
                              >
                                <ArrowDownIcon />
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label={`${t("actions.removeWorker")} ${worker.name}`}
                                onClick={() => removeWorker(index)}
                              >
                                <Trash2Icon />
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="border-b">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <CardTitle>
                        {selected?.visual.name ||
                          selected?.name ||
                          selectedRaw?.path ||
                          t("editor.configuration")}
                      </CardTitle>
                      <CardDescription className="mt-1">
                        {selected?.path ?? selectedRaw?.path}
                      </CardDescription>
                    </div>
                    {selected && (
                      <Badge variant="secondary">
                        {selected.path === coordinator?.path
                          ? t("editor.coordinator")
                          : t("editor.worker")}
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="pt-5">
                  <Tabs value={mode} onValueChange={setMode}>
                    <TabsList>
                      <TabsTrigger value="visual">{t("editor.visual")}</TabsTrigger>
                      <TabsTrigger value="yaml">{t("editor.yaml")}</TabsTrigger>
                    </TabsList>
                    <TabsContent value="visual" className="mt-5">
                      {selected ? (
                        <AgentConfigEditor
                          key={selected.path}
                          schema={formSchema.data}
                          harnesses={bundleOptions.data?.harnesses}
                          models={modelOptions}
                          skills={bundleOptions.data?.skills}
                          runtimeSkills={hostSkills.data}
                          runtimeLabel={
                            previewHost && previewHarness
                              ? `${previewHarness} (${previewHost.name})`
                              : undefined
                          }
                          bundledSkills={bundledSkillNames(selected.path, bundle.data.files)}
                          workerNames={workers.map(draftWorkerName)}
                          value={selected.visual}
                          onChange={(visual) =>
                            updateSelected((file) => ({ ...file, visual, visualDirty: true }))
                          }
                          disabled={readonly}
                        />
                      ) : selectedRaw ? (
                        <p className="text-sm text-muted-foreground">
                          {selectedRaw.inline
                            ? t("editor.yamlHelp")
                            : t("editor.fileNotInline", { size: selectedRaw.size })}
                        </p>
                      ) : (
                        <p>{t("errors.noCoordinator")}</p>
                      )}
                    </TabsContent>
                    <TabsContent value="yaml" className="mt-5 space-y-3">
                      <p className="text-xs text-muted-foreground">{t("editor.yamlHelp")}</p>
                      <div className="flex flex-wrap gap-1">
                        {[...allFiles, ...rawFiles].map((file) => (
                          <Button
                            key={file.path}
                            size="sm"
                            variant={file.path === selectedPath ? "secondary" : "ghost"}
                            onClick={() => setSelectedPath(file.path)}
                          >
                            {file.path}
                          </Button>
                        ))}
                      </div>
                      {selected && (
                        <Textarea
                          aria-label={selected.path}
                          className="min-h-[32rem] font-mono text-xs"
                          value={selected.yaml}
                          onChange={(event) => updateSelectedYaml(event.target.value)}
                          disabled={readonly || selected.pending || selected.visualDirty}
                        />
                      )}
                      {visualDirtyTargets.has(selectedPath) && (
                        <p role="status" className="text-sm text-muted-foreground">
                          {t("editor.visualDirtyYamlBlocked")}
                        </p>
                      )}
                      {selected?.yamlDiagnostic && (
                        <p role="alert" className="text-sm text-destructive">
                          {t("editor.invalidYaml", {
                            line: selected.yamlDiagnostic.line,
                            column: selected.yamlDiagnostic.column,
                          })}
                        </p>
                      )}
                      {selectedRaw && selectedRaw.yaml !== null && (
                        <Textarea
                          aria-label={selectedRaw.path}
                          className="min-h-[32rem] font-mono text-xs"
                          value={selectedRaw.yaml}
                          onChange={(event) => updateSelectedRaw(event.target.value)}
                          disabled={readonly || visualDirtyTargets.has(selectedRaw.path)}
                        />
                      )}
                      {selectedRaw && !selectedRaw.inline && (
                        <p role="status" className="text-sm text-muted-foreground">
                          {t("editor.fileNotInline", { size: selectedRaw.size })}
                        </p>
                      )}
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </div>

            <AgentFeishuPairingDialog
              agentId={bundle.data.card.id}
              agentName={bundle.data.card.name}
              open={feishuOpen}
              onOpenChange={setFeishuOpen}
            />
          </div>
        )
      )}
    </PageScroll>
  );
}
