import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDownIcon,
  ArrowLeftIcon,
  ArrowUpIcon,
  BotIcon,
  LinkIcon,
  PlusIcon,
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import { AgentConfigEditor } from "@/components/multi-agent/AgentConfigEditor";
import { BundleDiagnostics } from "@/components/multi-agent/BundleDiagnostics";
import { WorkspaceRunPanel } from "@/components/multi-agent/WorkspaceRunPanel";
import { PageScroll } from "@/components/PageScroll";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  useAgentFormSchema,
  useConnectMultiAgentFeishu,
  useCreateMultiAgent,
  useMultiAgent,
  useUpdateMultiAgent,
} from "@/hooks/useMultiAgents";
import {
  buildConfigPatches,
  DraftJsonError,
  readAgentConfig,
  workerName,
  type AgentConfigDraft,
} from "@/lib/multiAgentDraft";
import {
  AgentBundleApiError,
  type AgentBundleFile,
  type AgentBundlePatch,
  type AgentBundleValue,
  type BundleDiagnostic,
  type WorkerOperation,
} from "@/lib/multiAgentApi";
import { Link, useNavigate, useParams } from "@/lib/routing";

interface EditableFile {
  path: string;
  name: string;
  original: AgentBundleValue;
  visual: AgentConfigDraft;
  yaml: string;
  yamlDirty: boolean;
  pending: boolean;
}

function editableFile(file: AgentBundleFile, pending = false): EditableFile | null {
  if (file.data === undefined || file.content == null) return null;
  return {
    path: file.path,
    name: workerName(file.path, file.data),
    original: file.data,
    visual: readAgentConfig(file.data),
    yaml: file.content,
    yamlDirty: false,
    pending,
  };
}

function workerOrderPatch(
  coordinator: EditableFile,
  workers: EditableFile[],
): AgentBundlePatch | null {
  if (coordinator.yamlDirty) return null;
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

function CreateBundleForm() {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const create = useCreateMultiAgent();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const draft = await create.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
      shape: "multi-agent",
    });
    navigate(`/multi-agents/${draft.agent.id}`);
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
          <Button type="submit" disabled={!name.trim() || create.isPending}>
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
  useAgentFormSchema(!isNew);
  const update = useUpdateMultiAgent();
  const connectFeishu = useConnectMultiAgentFeishu();
  const [mode, setMode] = useState("visual");
  const [coordinator, setCoordinator] = useState<EditableFile | null>(null);
  const [workers, setWorkers] = useState<EditableFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>("config.yaml");
  const [workerOperations, setWorkerOperations] = useState<WorkerOperation[]>([]);
  const [diagnostics, setDiagnostics] = useState<BundleDiagnostic[]>([]);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [initializedVersion, setInitializedVersion] = useState<string | null>(null);
  const [feishuStatus, setFeishuStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!bundle.data) return;
    const key = `${bundle.data.agent.id}:${bundle.data.version}`;
    if (key === initializedVersion) return;
    setInitializedVersion(key);
    setCoordinator(bundle.data.coordinator ? editableFile(bundle.data.coordinator) : null);
    setWorkers(
      bundle.data.workers
        .map((file) => editableFile(file))
        .filter((file): file is EditableFile => file !== null),
    );
    setSelectedPath(bundle.data.coordinator?.path ?? bundle.data.workers[0]?.path ?? "config.yaml");
    setDiagnostics(bundle.data.diagnostics);
    setFeishuStatus(bundle.data.agent.feishu_status);
    setWorkerOperations([]);
  }, [bundle.data, initializedVersion]);

  const allFiles = useMemo(
    () => [coordinator, ...workers].filter((file): file is EditableFile => file !== null),
    [coordinator, workers],
  );
  const selected = allFiles.find((file) => file.path === selectedPath) ?? coordinator ?? workers[0];
  const readonly = bundle.data?.agent.editable === false;

  function updateSelected(transform: (file: EditableFile) => EditableFile) {
    if (!selected) return;
    if (coordinator?.path === selected.path) setCoordinator(transform(coordinator));
    else
      setWorkers((items) =>
        items.map((item) => (item.path === selected.path ? transform(item) : item)),
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
      visual: readAgentConfig(original),
      yaml: `name: ${name}\n`,
      yamlDirty: false,
      pending: true,
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

  async function save() {
    if (!agentId || !bundle.data || !coordinator || readonly) return;
    setSaveMessage(null);
    setSaveError(null);
    try {
      const patches = allFiles.flatMap((file) => {
        if (file.pending) return [];
        if (file.yamlDirty)
          return [{ file: file.path, op: "replace_file" as const, value: file.yaml }];
        return buildConfigPatches(file.path, file.original, file.visual);
      });
      const order = workerOrderPatch(
        coordinator,
        workers.filter((worker) => !worker.pending),
      );
      if (order) patches.push(order);
      const saved = await update.mutateAsync({
        agent_id: agentId,
        request: {
          expected_version: bundle.data.version,
          ...(patches.length ? { patches } : {}),
          ...(workerOperations.length ? { worker_operations: workerOperations } : {}),
        },
      });
      setDiagnostics(saved.diagnostics);
      setWorkerOperations([]);
      setSaveMessage(t("editor.saved"));
    } catch (error) {
      if (error instanceof DraftJsonError) {
        setSaveError(t("errors.invalidJson", { field: t(`fields.${error.field}`) }));
      } else {
        if (error instanceof AgentBundleApiError) setDiagnostics(error.diagnostics);
        setSaveError(error instanceof Error ? error.message : t("errors.action"));
      }
    }
  }

  async function connect() {
    if (!agentId) return;
    setFeishuStatus("pending");
    try {
      const result = await connectFeishu.mutateAsync(agentId);
      setFeishuStatus(result.status);
    } catch {
      setFeishuStatus("error");
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
      <Button asChild variant="ghost" size="sm" className="-ml-3 mb-4">
        <Link to="/multi-agents" aria-label={t("actions.back")}>
          <ArrowLeftIcon />
          {t("actions.back")}
        </Link>
      </Button>
      {isNew ? (
        <CreateBundleForm />
      ) : (
        bundle.data && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold">{bundle.data.agent.name}</h1>
                  {bundle.data.agent.builtin && (
                    <Badge variant="secondary">{t("catalog.builtinReadonly")}</Badge>
                  )}
                  <Badge
                    variant={
                      bundle.data.agent.validation_status === "invalid" ? "destructive" : "outline"
                    }
                  >
                    {t(`status.${bundle.data.agent.validation_status}`)}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {bundle.data.agent.description}
                </p>
                <p className="mt-2 font-mono text-xs text-muted-foreground">
                  v{bundle.data.version} · {bundle.data.digest}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={feishuStatus === "error" ? "destructive" : "outline"}>
                  {t(`status.${feishuStatus ?? "disconnected"}`)}
                </Badge>
                <Button
                  variant="outline"
                  onClick={() => void connect()}
                  disabled={connectFeishu.isPending}
                >
                  <LinkIcon />{" "}
                  {connectFeishu.isPending ? t("feishu.connecting") : t("feishu.connect")}
                </Button>
                {!readonly && (
                  <Button onClick={() => void save()} disabled={update.isPending}>
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

            <div className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
              <Card className="self-start">
                <CardHeader>
                  <CardTitle>{t("editor.coordinator")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {coordinator && (
                    <Button
                      className="w-full justify-start"
                      variant={selected?.path === coordinator.path ? "secondary" : "ghost"}
                      onClick={() => setSelectedPath(coordinator.path)}
                    >
                      <BotIcon />
                      {coordinator.name || t("editor.coordinator")}
                    </Button>
                  )}
                  <div className="flex items-center justify-between pt-3">
                    <span className="text-xs font-medium text-muted-foreground">
                      {t("editor.workers")}
                    </span>
                    {!readonly && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("actions.addWorker")}
                        onClick={addWorker}
                      >
                        <PlusIcon />
                      </Button>
                    )}
                  </div>
                  {workers.length === 0 && (
                    <p className="text-xs text-muted-foreground">{t("workers.empty")}</p>
                  )}
                  {workers.map((worker, index) => (
                    <div key={worker.path} className="flex items-center gap-1">
                      <Button
                        className="min-w-0 flex-1 justify-start truncate"
                        variant={selected?.path === worker.path ? "secondary" : "ghost"}
                        onClick={() => setSelectedPath(worker.path)}
                      >
                        {worker.name}
                      </Button>
                      {!readonly && (
                        <>
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
                        </>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{selected?.name ?? t("editor.configuration")}</CardTitle>
                  <CardDescription>{selected?.path}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Tabs value={mode} onValueChange={setMode}>
                    <TabsList>
                      <TabsTrigger value="visual">{t("editor.visual")}</TabsTrigger>
                      <TabsTrigger value="yaml">{t("editor.yaml")}</TabsTrigger>
                    </TabsList>
                    <TabsContent value="visual" className="mt-5">
                      {selected ? (
                        <AgentConfigEditor
                          value={selected.visual}
                          onChange={(visual) => updateSelected((file) => ({ ...file, visual }))}
                          disabled={readonly || selected.pending}
                        />
                      ) : (
                        <p>{t("errors.noCoordinator")}</p>
                      )}
                      {selected?.pending && (
                        <p className="mt-3 text-xs text-muted-foreground">
                          {t("workers.saveBeforeEditing")}
                        </p>
                      )}
                    </TabsContent>
                    <TabsContent value="yaml" className="mt-5 space-y-3">
                      <p className="text-xs text-muted-foreground">{t("editor.yamlHelp")}</p>
                      <div className="flex flex-wrap gap-1">
                        {allFiles.map((file) => (
                          <Button
                            key={file.path}
                            size="sm"
                            variant={file.path === selected?.path ? "secondary" : "ghost"}
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
                          onChange={(event) =>
                            updateSelected((file) => ({
                              ...file,
                              yaml: event.target.value,
                              yamlDirty: true,
                            }))
                          }
                          disabled={readonly || selected.pending}
                        />
                      )}
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>{t("feishu.title")}</CardTitle>
                <CardDescription>{t("feishu.description")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Badge variant={feishuStatus === "error" ? "destructive" : "outline"}>
                  {t(`status.${feishuStatus ?? "disconnected"}`)}
                </Badge>
              </CardContent>
            </Card>
            <WorkspaceRunPanel agentId={bundle.data.agent.id} />
          </div>
        )
      )}
    </PageScroll>
  );
}
