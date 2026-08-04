import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { QRCodeSVG } from "qrcode.react";
import { BotIcon, CheckCircle2Icon, ExternalLinkIcon, RefreshCwIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAgentFeishuConnection,
  useAgentFeishuSurface,
  useBeginAgentFeishu,
  useBindAgentFeishuWorkspace,
  useDisconnectAgentFeishu,
  useReinitializeAgentFeishuSurface,
} from "@/hooks/useFeishuInstall";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import type { AgentFeishuInstallation, AgentFeishuSurface } from "@/lib/feishuApi";

const ACTIONS = [
  "switchWorkspace",
  "createTask",
  "currentRun",
  "taskList",
  "logs",
  "approve",
  "deny",
  "stopRun",
  "help",
] as const;

function verificationUri(installation: AgentFeishuInstallation): string | null {
  return installation.verification_uri_complete ?? installation.verification_uri ?? null;
}

function verificationCode(installation: AgentFeishuInstallation): string {
  if (installation.user_code) return installation.user_code;
  const uri = verificationUri(installation);
  if (uri) {
    try {
      return new URL(uri).searchParams.get("user_code") ?? installation.session ?? "—";
    } catch {
      // Fall back to the device session for non-standard provider URLs.
    }
  }
  return installation.session ?? installation.device_session ?? "—";
}

function surfaceState(surface: AgentFeishuSurface | undefined): string {
  return surface?.status ?? "pending";
}

export function AgentFeishuPairingDialog({
  agentId,
  agentName,
  open,
  onOpenChange,
  onStatusChange,
}: {
  agentId: string;
  agentName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStatusChange?: (status: string) => void;
}) {
  const { t } = useTranslation("agents", { keyPrefix: "multiAgent.feishu" });
  const connection = useAgentFeishuConnection(agentId, open);
  const begin = useBeginAgentFeishu();
  const disconnect = useDisconnectAgentFeishu();
  const bindWorkspace = useBindAgentFeishuWorkspace();
  const workspaces = useWorkspaces(open);
  const installation = connection.data ?? null;
  const connected = installation?.status === "connected";
  const surface = useAgentFeishuSurface(agentId, open && connected);
  const reinitialize = useReinitializeAgentFeishuSurface();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("");
  const [grantClock, setGrantClock] = useState(() => Date.now());
  const session = installation?.session ?? installation?.device_session ?? "";
  const grantDeadline = useMemo(
    () =>
      installation?.status === "pending" && installation.expires_in && session
        ? Date.now() + installation.expires_in * 1_000
        : null,
    [installation?.expires_in, installation?.status, session],
  );
  useEffect(() => {
    if (!open || installation?.status !== "pending") return;
    const timer = window.setInterval(() => setGrantClock(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [installation?.status, open]);
  useEffect(() => {
    if (installation?.status) onStatusChange?.(installation.status);
  }, [installation?.status, onStatusChange]);
  useEffect(() => {
    if (selectedWorkspaceId) return;
    setSelectedWorkspaceId(installation?.binding?.workspace_id ?? workspaces.data?.[0]?.id ?? "");
  }, [installation?.binding?.workspace_id, selectedWorkspaceId, workspaces.data]);

  const selectedWorkspace = workspaces.data?.find(
    (workspace) => workspace.id === selectedWorkspaceId,
  );
  const expiresIn = grantDeadline
    ? Math.max(0, Math.ceil((grantDeadline - grantClock) / 1_000))
    : (installation?.expires_in ?? null);
  const expired = installation?.status === "expired" || expiresIn === 0;
  const qrUri = installation ? verificationUri(installation) : null;
  const displayedSurface = surface.data ?? installation?.surface ?? undefined;
  const provider = useMemo(
    () => ({
      tenant: installation?.tenant_name ?? installation?.tenant_key ?? installation?.app_id,
      bot: installation?.bot_name ?? installation?.bot_open_id,
    }),
    [installation],
  );

  async function selectWorkspace(workspaceId: string) {
    setSelectedWorkspaceId(workspaceId);
    const binding = installation?.binding;
    if (!installation || !binding?.chat_id) return;
    await bindWorkspace.mutateAsync({
      agentId,
      input: {
        installation_id: installation.id,
        chat_id: binding.chat_id,
        thread_id: binding.thread_id,
        workspace_id: workspaceId,
        host_id: binding.host_id,
        execution_mode: binding.execution_mode ?? "auto",
      },
    });
  }

  async function disconnectCurrent() {
    await disconnect.mutateAsync(agentId);
    onStatusChange?.("disconnected");
  }

  const operationError =
    begin.error ??
    disconnect.error ??
    bindWorkspace.error ??
    reinitialize.error ??
    surface.error ??
    connection.error;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("connect")}</DialogTitle>
          <DialogDescription>{t("modalDescription", { agent: agentName })}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3">
          <div>
            <p className="font-medium">{t("coordinatorConnection")}</p>
            <p className="text-xs text-muted-foreground">{t("coordinatorOnly")}</p>
          </div>
          <Badge variant={installation?.status === "error" ? "destructive" : "outline"}>
            {t(`states.${installation?.status ?? "disconnected"}`)}
          </Badge>
        </div>

        {!installation && !connection.isLoading && (
          <div className="space-y-3 rounded-lg border border-dashed p-5 text-center">
            <BotIcon className="mx-auto size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{t("notConnected")}</p>
            <Button onClick={() => void begin.mutateAsync(agentId)} disabled={begin.isPending}>
              {begin.isPending ? t("creatingGrant") : t("createGrant")}
            </Button>
          </div>
        )}

        {installation?.status === "pending" && !expired && (
          <div className="grid gap-5 rounded-lg border p-4 sm:grid-cols-[12rem_1fr]">
            {qrUri && (
              <div
                role="img"
                aria-label={t("qrLabel")}
                className="flex size-48 items-center justify-center rounded-lg border bg-white p-3"
              >
                <QRCodeSVG value={qrUri} size={168} />
              </div>
            )}
            <div className="space-y-3">
              <div>
                <p className="font-medium">{t("scanTitle")}</p>
                <p className="text-sm text-muted-foreground">{t("scanHelp")}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("verificationCode")}</p>
                <code className="text-lg font-semibold tracking-widest">
                  {verificationCode(installation)}
                </code>
              </div>
              {expiresIn != null && (
                <p className="text-sm">{t("expiresIn", { seconds: expiresIn })}</p>
              )}
              {qrUri && (
                <Button asChild size="sm" variant="outline">
                  <a href={qrUri} target="_blank" rel="noreferrer">
                    <ExternalLinkIcon /> {t("openVerification")}
                  </a>
                </Button>
              )}
              <p role="status" className="text-xs text-muted-foreground">
                {t("waiting")}
              </p>
            </div>
          </div>
        )}

        {(expired || installation?.status === "error") && (
          <div className="space-y-3 rounded-lg border border-destructive/40 p-4">
            <p role="alert" className="text-sm text-destructive">
              {installation?.error || t(expired ? "grantExpired" : "connectionFailed")}
            </p>
            <Button onClick={() => void begin.mutateAsync(agentId)} disabled={begin.isPending}>
              <RefreshCwIcon /> {t("retryConnection")}
            </Button>
          </div>
        )}

        {connected && installation && (
          <div className="space-y-4">
            <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
              <div>
                <p className="text-xs text-muted-foreground">{t("tenant")}</p>
                <p className="font-mono text-sm">{provider.tenant || t("unknown")}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("bot")}</p>
                <p className="font-mono text-sm">{provider.bot || t("unknown")}</p>
              </div>
            </div>

            <div className="space-y-2 rounded-lg border p-4">
              <label htmlFor="feishu-default-workspace" className="font-medium">
                {t("defaultWorkspace")}
              </label>
              <select
                id="feishu-default-workspace"
                className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm"
                value={selectedWorkspaceId}
                onChange={(event) => void selectWorkspace(event.target.value)}
                disabled={bindWorkspace.isPending}
              >
                <option value="">{t("selectWorkspace")}</option>
                {workspaces.data?.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.root_path}
                  </option>
                ))}
              </select>
              {selectedWorkspace && (
                <p className="text-xs text-muted-foreground">
                  {t("repositorySummary", {
                    count: selectedWorkspace.repositories.length,
                    repositories:
                      selectedWorkspace.repositories
                        .map((repository) => repository.name)
                        .join(", ") || "—",
                  })}
                </p>
              )}
              {!installation.binding?.chat_id && (
                <p className="text-xs text-muted-foreground">{t("bindingPending")}</p>
              )}
            </div>

            <div className="space-y-3 rounded-lg border p-4">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="font-medium">{t("surfaceTitle")}</p>
                  <p className="text-xs text-muted-foreground">{t("surfaceDescription")}</p>
                </div>
                <Badge variant={displayedSurface?.status === "failed" ? "destructive" : "outline"}>
                  {t(`surfaceStates.${surfaceState(displayedSurface)}`)}
                </Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {ACTIONS.map((action) => {
                  const contextual = action === "approve" || action === "deny";
                  const status = contextual ? "contextual" : surfaceState(displayedSurface);
                  return (
                    <div
                      key={action}
                      className="flex items-center gap-2 rounded-md bg-muted/50 p-2"
                    >
                      <CheckCircle2Icon className="size-4 text-muted-foreground" />
                      <span className="min-w-0 flex-1 text-xs">{t(`actions.${action}`)}</span>
                      <Badge variant="outline" className="text-10">
                        {t(`surfaceStates.${status}`)}
                      </Badge>
                    </div>
                  );
                })}
              </div>
              {displayedSurface?.error && (
                <p role="alert" className="text-sm text-destructive">
                  {displayedSurface.error}
                </p>
              )}
              {(displayedSurface?.status === "partial" ||
                displayedSurface?.status === "failed") && (
                <Button
                  variant="outline"
                  onClick={() => void reinitialize.mutateAsync(agentId)}
                  disabled={reinitialize.isPending}
                >
                  <RefreshCwIcon />
                  {reinitialize.isPending ? t("provisioning") : t("retryProvisioning")}
                </Button>
              )}
              <p className="text-xs text-muted-foreground">{t("stateSource")}</p>
            </div>

            <Button
              variant="destructive"
              onClick={() => void disconnectCurrent()}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? t("disconnecting") : t("disconnect")}
            </Button>
          </div>
        )}

        {operationError && (
          <p role="alert" className="text-sm text-destructive">
            {operationError.message}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
