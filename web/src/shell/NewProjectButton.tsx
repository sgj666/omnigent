import { useEffect, useMemo, useState } from "react";
import { FolderIcon, MonitorIcon, PlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCreateProject } from "@/hooks/useConversations";
import { useHosts } from "@/hooks/useHosts";
import { useTranslation } from "react-i18next";
import "@/i18n";
import { isNavigablePath, WorkspacePicker } from "./WorkspacePicker";

/**
 * "New project" control in the Projects group header. Opens a dialog that
 * creates a first-class project with its execution Host and source folder
 * bound (`POST /v1/projects`). On success the new folder is expanded (via
 * `onCreated`) so the user can immediately start sessions in it.
 */
export function NewProjectButton({ onCreated }: { onCreated: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [hostId, setHostId] = useState("");
  const [workspace, setWorkspace] = useState("");
  const createProject = useCreateProject();
  const hosts = useHosts({ enabled: open });
  const { t } = useTranslation("common");
  const onlineHosts = useMemo(
    () => (hosts.data ?? []).filter((host) => host.status === "online"),
    [hosts.data],
  );

  // A single connected machine is the common local setup. Select it as soon
  // as the dialog opens so the primary action remains "pick a source folder",
  // matching the Codex project flow while still preserving Omnigent's
  // multi-host identity in the stored Project binding.
  useEffect(() => {
    if (!open || hostId !== "" || onlineHosts.length !== 1) return;
    setHostId(onlineHosts[0].host_id);
  }, [hostId, onlineHosts, open]);

  const submit = () => {
    const trimmed = name.trim();
    const trimmedWorkspace = workspace.trim();
    if (trimmed === "" || hostId === "" || !isNavigablePath(trimmedWorkspace)) return;
    createProject.mutate(
      {
        name: trimmed,
        config: { host_id: hostId, workspace: trimmedWorkspace },
      },
      {
        onSuccess: (project) => {
          setOpen(false);
          setName("");
          setHostId("");
          setWorkspace("");
          onCreated(project.name);
        },
      },
    );
  };

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={t("shell.newProject")}
            data-testid="new-project"
            onClick={(e) => {
              e.stopPropagation();
              setName("");
              setHostId("");
              setWorkspace("");
              setOpen(true);
            }}
          >
            <PlusIcon className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">{t("shell.newProjectTooltip")}</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()} className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("shell.newProject")}</DialogTitle>
            <DialogDescription>{t("shell.newProjectDescription")}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("shell.projectName")}</span>
              <input
                autoFocus
                className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none"
                placeholder={t("shell.projectNamePlaceholder")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("shell.projectHost")}</span>
              <Select
                value={hostId}
                onValueChange={(next) => {
                  setHostId(next);
                  setWorkspace("");
                }}
              >
                <SelectTrigger data-testid="new-project-host">
                  <SelectValue placeholder={t("shell.projectHostPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {onlineHosts.map((host) => (
                    <SelectItem key={host.host_id} value={host.host_id}>
                      <span className="flex items-center gap-2">
                        <MonitorIcon className="size-4 text-muted-foreground" />
                        {host.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>

            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("shell.projectSourceFolder")}</span>
              {hostId ? (
                <div className="overflow-hidden rounded-lg border" data-testid="new-project-folder">
                  <WorkspacePicker
                    hostId={hostId}
                    initialPath={isNavigablePath(workspace) ? workspace : undefined}
                    onNavigate={setWorkspace}
                  />
                </div>
              ) : (
                <div className="flex min-h-28 items-center justify-center rounded-lg border bg-muted/40 px-4 text-center text-sm text-muted-foreground">
                  <span className="flex items-center gap-2">
                    <FolderIcon className="size-4" />
                    {onlineHosts.length === 0
                      ? t("shell.projectNoOnlineHost")
                      : t("shell.projectChooseHostFirst")}
                  </span>
                </div>
              )}
              {workspace && (
                <p className="truncate text-xs text-muted-foreground" title={workspace}>
                  {workspace}
                </p>
              )}
            </div>
          </div>
          {createProject.isError && (
            <p className="text-sm text-destructive" role="alert">
              {t("shell.projectCreateFailed", {
                message: (createProject.error as Error).message,
              })}
            </p>
          )}
          <DialogFooter className="border-t-0 bg-transparent">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={createProject.isPending}
            >
              {t("shell.cancel")}
            </Button>
            <Button
              type="button"
              data-testid="new-project-confirm"
              disabled={
                createProject.isPending ||
                name.trim() === "" ||
                hostId === "" ||
                !isNavigablePath(workspace.trim())
              }
              onClick={submit}
            >
              {createProject.isPending ? t("shell.creating") : t("shell.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
