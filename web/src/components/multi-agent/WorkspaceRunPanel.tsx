import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FolderGit2Icon, PlayIcon, PlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useHosts } from "@/hooks/useHosts";
import { useCreateWorkspace, useWorkspaces } from "@/hooks/useWorkspaces";
import { startMultiAgentRun } from "@/lib/multiAgentApi";
import { useNavigate } from "@/lib/routing";

export function WorkspaceRunPanel({
  agentId,
  disabled = false,
}: {
  agentId: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent" });
  const workspaces = useWorkspaces();
  const createWorkspace = useCreateWorkspace();
  const hosts = useHosts({ refetchOnFocus: true });
  const navigate = useNavigate();
  const [workspaceId, setWorkspaceId] = useState("");
  const [hostId, setHostId] = useState("");
  const [rootPath, setRootPath] = useState("");
  const [taskInput, setTaskInput] = useState("");
  const [runError, setRunError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const sourceEventId = useRef<string | null>(null);

  useEffect(() => {
    if (!workspaceId && workspaces.data?.[0]) setWorkspaceId(workspaces.data[0].id);
  }, [workspaceId, workspaces.data]);
  useEffect(() => {
    if (!hostId) {
      const online = hosts.data?.find((host) => host.status === "online");
      if (online) setHostId(online.host_id);
    }
  }, [hostId, hosts.data]);

  const selected = workspaces.data?.find((workspace) => workspace.id === workspaceId);

  async function registerWorkspace() {
    if (!rootPath.trim()) return;
    const workspace = await createWorkspace.mutateAsync({ root_path: rootPath.trim() });
    setWorkspaceId(workspace.id);
    setRootPath("");
  }

  async function run() {
    if (!selected || !hostId || !taskInput.trim()) return;
    setRunError(null);
    setStarting(true);
    sourceEventId.current ??= `web:${crypto.randomUUID()}`;
    try {
      const started = await startMultiAgentRun({
        agent_id: agentId,
        workspace_id: selected.id,
        input: taskInput.trim(),
        source: "web",
        source_event_id: sourceEventId.current,
        host_id: hostId,
        execution_mode: "auto",
      });
      sourceEventId.current = null;
      navigate(`/runs/${started.id}`);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : t("workspace.runFailed"));
    } finally {
      setStarting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("workspace.title")}</CardTitle>
        <CardDescription>{t("workspace.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            aria-label={t("workspace.localDirectory")}
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
            placeholder="/Users/you/project"
            disabled={disabled}
          />
          <Button
            variant="outline"
            onClick={() => void registerWorkspace()}
            disabled={disabled || !rootPath.trim() || createWorkspace.isPending}
          >
            <PlusIcon /> {t("workspace.register")}
          </Button>
        </div>
        {workspaces.isLoading && (
          <p className="text-sm text-muted-foreground">{t("workspace.loading")}</p>
        )}
        {!workspaces.isLoading && !workspaces.data?.length && (
          <p className="text-sm text-muted-foreground">{t("workspace.empty")}</p>
        )}
        {!!workspaces.data?.length && (
          <div className="grid gap-2 sm:grid-cols-2">
            {workspaces.data.map((workspace) => (
              <button
                key={workspace.id}
                type="button"
                onClick={() => setWorkspaceId(workspace.id)}
                className={`rounded-lg border p-3 text-left transition-colors ${workspaceId === workspace.id ? "border-primary bg-primary/5" : "border-border/70 hover:bg-muted/40"}`}
              >
                <div className="flex items-center gap-2 font-mono text-xs">
                  <FolderGit2Icon className="size-4" />
                  {workspace.root_path}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{t("workspace.repositories")}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {workspace.repositories.length === 0 ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : (
                    workspace.repositories.map((repo) => (
                      <span
                        key={`${repo.name}-${repo.path}`}
                        className="rounded bg-muted px-1.5 py-0.5 text-xs"
                        title={repo.path}
                      >
                        {repo.name}
                      </span>
                    ))
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
        <div className="space-y-1.5">
          <label
            htmlFor="multi-agent-run-input"
            className="text-xs font-medium text-muted-foreground"
          >
            {t("workspace.taskInput")}
          </label>
          <Textarea
            id="multi-agent-run-input"
            value={taskInput}
            onChange={(event) => setTaskInput(event.target.value)}
            placeholder={t("workspace.taskInputPlaceholder")}
            disabled={disabled}
            rows={3}
          />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-52 flex-1 space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              {t("workspace.host")}
            </label>
            <Select value={hostId} onValueChange={setHostId} disabled={disabled}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={t("workspace.selectHost")} />
              </SelectTrigger>
              <SelectContent>
                {hosts.data?.map((host) => (
                  <SelectItem
                    key={host.host_id}
                    value={host.host_id}
                    disabled={host.status !== "online"}
                  >
                    {host.name} · {host.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            onClick={() => void run()}
            disabled={disabled || !selected || !hostId || !taskInput.trim() || starting}
          >
            <PlayIcon /> {starting ? t("workspace.starting") : t("workspace.run")}
          </Button>
        </div>
        {runError && (
          <p role="alert" className="text-sm text-destructive">
            {t("workspace.runFailed")}: {runError}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
