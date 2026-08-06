import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { QRCodeSVG } from "qrcode.react";
import {
  ActivityIcon,
  BoltIcon,
  BotIcon,
  ExternalLinkIcon,
  FolderIcon,
  HelpCircleIcon,
  MonitorIcon,
  RefreshCwIcon,
  SquareIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAgentDefaultWorkspaceScope,
  useAgentFeishuConnection,
  useAgentFeishuSurfaceProfile,
  useBeginAgentFeishu,
  useDisconnectAgentFeishu,
  useSetAgentDefaultWorkspaceScope,
  useSetAgentFeishuSurfaceProfile,
} from "@/hooks/useFeishuInstall";
import { useHosts } from "@/hooks/useHosts";
import type {
  AgentFeishuInstallation,
  AgentFeishuSurfaceAction,
  AgentFeishuSurfaceProfile,
} from "@/lib/feishuApi";
import { WorkspacePicker } from "@/shell/WorkspacePicker";

const DEFAULT_ACTIONS: AgentFeishuSurfaceAction[] = [
  "quick_commands",
  "manage_devices",
  "switch_workspace",
];

const ACTIONS = [
  { id: "quick_commands", icon: BoltIcon },
  { id: "manage_devices", icon: MonitorIcon },
  { id: "switch_workspace", icon: FolderIcon },
  { id: "current_run", icon: ActivityIcon },
  { id: "stop_session", icon: SquareIcon },
  { id: "help", icon: HelpCircleIcon },
] satisfies { id: AgentFeishuSurfaceAction; icon: typeof BoltIcon }[];

const MENU_EVENT_KEYS: Record<AgentFeishuSurfaceAction, string[]> = {
  quick_commands: ["session_new", "session_stop"],
  manage_devices: ["manage_devices"],
  switch_workspace: ["switch_workspace"],
  current_run: ["current_run"],
  stop_session: ["session_stop"],
  help: ["help"],
};

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
  const profile = useAgentFeishuSurfaceProfile(agentId, open);
  const defaultScope = useAgentDefaultWorkspaceScope(agentId, open);
  const begin = useBeginAgentFeishu();
  const disconnect = useDisconnectAgentFeishu();
  const setDefaultScope = useSetAgentDefaultWorkspaceScope();
  const setProfile = useSetAgentFeishuSurfaceProfile();
  const { data: hosts } = useHosts({ enabled: open });
  const installation = connection.data ?? null;
  const connected = installation?.status === "connected";
  const [workspacePath, setWorkspacePath] = useState("");
  const [selectedHostId, setSelectedHostId] = useState("");
  const [detailsBaseUrl, setDetailsBaseUrl] = useState(() => window.location.origin);
  const [selectedActions, setSelectedActions] =
    useState<AgentFeishuSurfaceAction[]>(DEFAULT_ACTIONS);
  const [pickingDirectory, setPickingDirectory] = useState(false);
  const [saved, setSaved] = useState(false);
  const [surfaceSync, setSurfaceSync] = useState<AgentFeishuSurfaceProfile["sync"]>();
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
    setWorkspacePath(defaultScope.data?.workspace ?? installation?.default_workspace ?? "");
  }, [agentId, defaultScope.data?.workspace, installation?.default_workspace]);
  useEffect(() => {
    const configured = defaultScope.data?.host_id ?? installation?.default_host_id;
    const fallback = hosts?.find((host) => host.status === "online")?.host_id;
    setSelectedHostId(configured ?? fallback ?? "");
  }, [agentId, defaultScope.data?.host_id, hosts, installation?.default_host_id]);
  useEffect(() => {
    if (!profile.data) return;
    setDetailsBaseUrl(profile.data.details_base_url || window.location.origin);
    setSelectedActions(profile.data.actions);
    setSurfaceSync(profile.data.sync);
  }, [agentId, profile.data]);

  const expiresIn = grantDeadline
    ? Math.max(0, Math.ceil((grantDeadline - grantClock) / 1_000))
    : (installation?.expires_in ?? null);
  const expired =
    installation?.status === "expired" || (installation?.status === "pending" && expiresIn === 0);
  const qrUri = installation ? verificationUri(installation) : null;
  const provider = {
    tenant: installation?.tenant_name ?? installation?.tenant_key ?? installation?.app_id,
    bot: installation?.bot_name ?? installation?.bot_open_id,
  };
  const validScope = selectedHostId !== "" && workspacePath.startsWith("/");
  const validDetailsUrl = /^https?:\/\//.test(detailsBaseUrl);
  const saving = setDefaultScope.isPending || setProfile.isPending;

  function toggleAction(action: AgentFeishuSurfaceAction) {
    setSaved(false);
    setSelectedActions((current) =>
      current.includes(action) ? current.filter((item) => item !== action) : [...current, action],
    );
  }

  async function saveConfiguration(startPairing = false) {
    if (!validScope || !validDetailsUrl) return;
    const [, savedProfile] = await Promise.all([
      setDefaultScope.mutateAsync({
        agentId,
        input: { workspace: workspacePath, host_id: selectedHostId },
      }),
      setProfile.mutateAsync({
        agentId,
        input: { details_base_url: detailsBaseUrl, actions: selectedActions },
      }),
    ]);
    setSurfaceSync(savedProfile?.sync);
    setSaved(true);
    if (startPairing) await begin.mutateAsync(agentId);
  }

  async function disconnectCurrent() {
    await disconnect.mutateAsync(agentId);
    onStatusChange?.("disconnected");
  }

  const operationError =
    begin.error ??
    disconnect.error ??
    setDefaultScope.error ??
    setProfile.error ??
    profile.error ??
    connection.error;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{connected ? t("manageConnection") : t("connect")}</DialogTitle>
          <DialogDescription>{t("modalDescription", { agent: agentName })}</DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
          <div>
            <p className="font-medium">{t("coordinatorConnection")}</p>
            <p className="text-xs text-muted-foreground">{t("coordinatorOnly")}</p>
          </div>
          <Badge variant={installation?.status === "error" ? "destructive" : "outline"}>
            {t(`states.${installation?.status ?? "disconnected"}`)}
          </Badge>
        </div>

        <section className="space-y-4 rounded-lg border p-4">
          <div>
            <p className="font-medium">{t("entrySettingsTitle")}</p>
            <p className="text-xs text-muted-foreground">{t("entrySettingsDescription")}</p>
          </div>

          <div className="space-y-2 rounded-lg bg-muted/40 p-3">
            <div className="flex items-start gap-3">
              <ExternalLinkIcon className="mt-0.5 size-5 text-blue-600" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium">{t("detailsEntry")}</p>
                  <Badge variant="secondary">{t("alwaysEnabled")}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{t("detailsEntryHelp")}</p>
              </div>
            </div>
            <Input
              aria-label={t("detailsBaseUrl")}
              value={detailsBaseUrl}
              placeholder="https://omnigent.example.com"
              onChange={(event) => {
                setSaved(false);
                setDetailsBaseUrl(event.target.value);
              }}
            />
            {detailsBaseUrl.includes("127.0.0.1") || detailsBaseUrl.includes("localhost") ? (
              <p className="text-xs text-amber-600">{t("localDetailsWarning")}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <div>
              <p className="text-sm font-medium">{t("quickEntries")}</p>
              <p className="text-xs text-muted-foreground">{t("quickEntriesHelp")}</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {ACTIONS.map(({ id, icon: Icon }) => {
                const checked = selectedActions.includes(id);
                return (
                  <label
                    key={id}
                    className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                      checked ? "border-blue-500 bg-blue-500/5" : "hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 size-4 accent-blue-600"
                      checked={checked}
                      onChange={() => toggleAction(id)}
                    />
                    <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{t(`entryActions.${id}`)}</span>
                      <span className="block text-xs text-muted-foreground">
                        {t(`entryActionHelp.${id}`)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground">{t("nativeMenuLimit")}</p>
          </div>

          <div className="space-y-3 rounded-lg border border-dashed p-3">
            <div className="flex items-start gap-3">
              <BotIcon className="mt-0.5 size-5 text-blue-600" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium">{t("floatingMenuTitle")}</p>
                  <Badge variant="outline">{t("manualPublish")}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{t("floatingMenuDescription")}</p>
              </div>
            </div>

            <div className="rounded-md bg-muted/40 p-3 text-xs">
              <p className="text-muted-foreground">{t("menuEventType")}</p>
              <code className="font-medium">application.bot.menu_v6</code>
            </div>

            <div className="space-y-2">
              {selectedActions.map((action) => (
                <div
                  key={action}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs"
                >
                  <span>{t(`entryActions.${action}`)}</span>
                  <span className="flex flex-wrap justify-end gap-1">
                    {MENU_EVENT_KEYS[action].map((eventKey) => (
                      <code key={eventKey} className="rounded bg-muted px-1.5 py-0.5">
                        {eventKey}
                      </code>
                    ))}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button asChild size="sm" variant="outline">
                <a
                  href={
                    installation?.app_id
                      ? `https://open.feishu.cn/app/${installation.app_id}`
                      : "https://open.feishu.cn/app"
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLinkIcon /> {t("openDeveloperConsole")}
                </a>
              </Button>
              <span className="text-xs text-muted-foreground">{t("menuPublishHint")}</span>
            </div>
            <p className="text-xs text-muted-foreground">{t("menuSingleChatHint")}</p>
          </div>
        </section>

        <section className="space-y-3 rounded-lg border p-4">
          <div>
            <p className="font-medium">{t("defaultScopeTitle")}</p>
            <p className="text-xs text-muted-foreground">{t("defaultScopeDescription")}</p>
          </div>
          <select
            aria-label={t("workingDirectoryHost")}
            className="h-8 w-full rounded-lg border border-input bg-background px-2 text-sm"
            value={selectedHostId}
            onChange={(event) => {
              setSaved(false);
              setSelectedHostId(event.target.value);
            }}
          >
            <option value="">{t("selectHost")}</option>
            {hosts
              ?.filter((host) => host.status === "online")
              .map((host) => (
                <option key={host.host_id} value={host.host_id}>
                  {host.name}
                </option>
              ))}
          </select>
          <Input
            aria-label={t("defaultScopeTitle")}
            value={workspacePath}
            placeholder="/Users/me/projects"
            onChange={(event) => {
              setSaved(false);
              setWorkspacePath(event.target.value);
            }}
          />
          <Button
            variant="outline"
            onClick={() => setPickingDirectory((value) => !value)}
            disabled={!selectedHostId}
          >
            <FolderIcon /> {t("browseDirectory")}
          </Button>
          {pickingDirectory && (
            <WorkspacePicker
              hostId={selectedHostId || null}
              initialPath={workspacePath || undefined}
              onSelect={(path) => {
                setSaved(false);
                setWorkspacePath(path);
                setPickingDirectory(false);
              }}
              onClose={() => setPickingDirectory(false)}
            />
          )}
          <p className="text-xs text-muted-foreground">{t("authorizedDirectoryHelp")}</p>
        </section>

        {!installation && !connection.isLoading && (
          <div className="space-y-3 rounded-lg border border-dashed p-5 text-center">
            <BotIcon className="mx-auto size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {validScope ? t("notConnected") : t("defaultScopeRequired")}
            </p>
            <Button
              onClick={() => void saveConfiguration(true)}
              disabled={saving || begin.isPending || !validScope || !validDetailsUrl}
            >
              {saving || begin.isPending ? t("creatingGrant") : t("saveAndCreateGrant")}
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
            <Button
              onClick={() => void saveConfiguration(true)}
              disabled={saving || begin.isPending || !validScope || !validDetailsUrl}
            >
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
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => void saveConfiguration(false)}
                disabled={saving || !validScope || !validDetailsUrl}
              >
                {saving ? t("savingConfiguration") : t("saveConfiguration")}
              </Button>
              {saved && <span className="text-sm text-emerald-600">{t("configurationSaved")}</span>}
              <Button
                variant="destructive"
                onClick={() => void disconnectCurrent()}
                disabled={disconnect.isPending}
              >
                {disconnect.isPending ? t("disconnecting") : t("disconnect")}
              </Button>
            </div>
            {surfaceSync?.status === "permission_required" && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                <p className="font-medium text-amber-700">{t("detailsPermissionRequired")}</p>
                <p className="text-xs text-muted-foreground">{surfaceSync.message}</p>
                {surfaceSync.permission_url && (
                  <Button asChild className="mt-2" size="sm" variant="outline">
                    <a href={surfaceSync.permission_url} target="_blank" rel="noreferrer">
                      <ExternalLinkIcon /> {t("openPermissionSettings")}
                    </a>
                  </Button>
                )}
              </div>
            )}
            {surfaceSync?.status === "ready" && (
              <p className="text-sm text-emerald-600">{t("detailsEntrySynced")}</p>
            )}
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
