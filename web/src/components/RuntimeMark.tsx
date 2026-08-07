import { BotIcon, CpuIcon } from "lucide-react";
import { AntigravityIcon } from "@/components/icons/AntigravityIcon";
import { ClaudeIcon } from "@/components/icons/ClaudeIcon";
import { CodexIcon } from "@/components/icons/CodexIcon";
import { CursorIcon } from "@/components/icons/CursorIcon";
import { GooseIcon } from "@/components/icons/GooseIcon";
import { HermesIcon } from "@/components/icons/HermesIcon";
import { KimiIcon } from "@/components/icons/KimiIcon";
import { KiroIcon } from "@/components/icons/KiroIcon";
import { OpenCodeIcon } from "@/components/icons/OpenCodeIcon";
import { PiIcon } from "@/components/icons/PiIcon";
import { cn } from "@/lib/utils";

function runtimeIcon(runtimeId: string) {
  if (runtimeId.startsWith("claude")) return ClaudeIcon;
  if (runtimeId.startsWith("codex")) return CodexIcon;
  if (runtimeId.startsWith("cursor")) return CursorIcon;
  if (runtimeId.startsWith("opencode")) return OpenCodeIcon;
  if (runtimeId.startsWith("pi")) return PiIcon;
  if (runtimeId.startsWith("kiro")) return KiroIcon;
  if (runtimeId.startsWith("goose")) return GooseIcon;
  if (runtimeId.startsWith("kimi")) return KimiIcon;
  if (runtimeId.startsWith("hermes")) return HermesIcon;
  if (runtimeId.startsWith("antigravity")) return AntigravityIcon;
  if (runtimeId === "openai-agents" || runtimeId === "open-responses") return BotIcon;
  return CpuIcon;
}

export function RuntimeMark({ runtimeId, className }: { runtimeId: string; className?: string }) {
  const Icon = runtimeIcon(runtimeId);
  return (
    <span
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-xl border bg-background text-foreground shadow-sm",
        className,
      )}
    >
      <Icon className="size-4.5" />
    </span>
  );
}
