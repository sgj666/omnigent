import { useState } from "react";
import { PlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCreateProject } from "@/hooks/useConversations";
import { useTranslation } from "react-i18next";
import "@/i18n";

/**
 * "New project" control in the Projects group header. Opens a dialog that
 * creates an EMPTY first-class project (`POST /v1/projects`) — the capability
 * the legacy label model can't express. On success the new folder is expanded
 * (via `onCreated`) so the user can immediately file sessions into it.
 */
export function NewProjectButton({ onCreated }: { onCreated: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const createProject = useCreateProject();
  const { t } = useTranslation("common");

  const submit = () => {
    const trimmed = name.trim();
    if (trimmed === "") return;
    createProject.mutate(trimmed, {
      onSuccess: (project) => {
        setOpen(false);
        setName("");
        onCreated(project.name);
      },
    });
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
              setOpen(true);
            }}
          >
            <PlusIcon className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">{t("shell.newProjectTooltip")}</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>{t("shell.newProject")}</DialogTitle>
            <DialogDescription>{t("shell.newProjectDescription")}</DialogDescription>
          </DialogHeader>
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
              disabled={createProject.isPending || name.trim() === ""}
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
