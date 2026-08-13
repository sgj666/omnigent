import {
  type DragEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "@/lib/routing";
import { useQueryClient } from "@tanstack/react-query";
import {
  MonitorIcon,
  MonitorCloudIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ArrowUpIcon,
  Loader2Icon,
  FileTextIcon,
  BriefcaseBusinessIcon,
  FolderIcon,
  ImageIcon,
  PaperclipIcon,
  PlusIcon,
  SettingsIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  CLAUDE_NATIVE_EFFORTS,
  ConfigRow,
  DescribedSelect,
  EFFORT_SELECT_NONE,
  MODEL_SELECT_DEFAULT,
  MODEL_SELECT_SMART,
  translateConfigOptionLabel,
} from "@/components/HarnessConfigControls";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { authenticatedFetch } from "@/lib/identity";
import { isImeCompositionKeyEvent } from "@/lib/ime";
import { attachmentKey } from "@/lib/attachments";
import { useServerInfo } from "@/lib/CapabilitiesContext";
import { HarnessSetupDialog } from "@/shell/HarnessSetupDialog";
import {
  harnessUnavailableReasonOnHost,
  harnessUnconfiguredOnHost,
  harnessWarningBadgeText,
  isCodexHarness,
  isNativeCursorHarness,
} from "@/lib/harnessSetup";

// Re-exported for tests that import the readiness helpers from this module.
export { harnessUnavailableReasonOnHost, harnessUnconfiguredOnHost, harnessWarningBadgeText };
import { sandboxOptionLabel } from "@/lib/capabilities";
import {
  isSlashCommandText,
  rankedSlashCommandNames,
  SlashCommandMenu,
} from "@/components/SlashCommandMenu";
import { setPendingInitialPrompt } from "@/store/chatStore";
import { appendPromptHistoryEntry } from "@/hooks/usePromptHistory";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { CliCommandBlock } from "./CliCommandBlock";
import {
  initialPrefillState,
  prefillDone,
  projectPrefillStep,
  type ProjectPrefillConfig,
  type ProjectPrefillState,
} from "./projectPrefill";
import { readLastAgentId, writeLastAgentId } from "@/lib/agentPreferences";
import { SANDBOX_HOST_CHOICE } from "@/lib/hostPreferences";
import { readLastHarness, writeLastHarness } from "@/lib/harnessPreferences";
import { readHideUnconfiguredHarnesses } from "@/lib/harnessVisibilityPreferences";
import { readDefaultBaseBranch } from "@/lib/baseBranchPreferences";
import { readHarnessOptions, writeHarnessOption } from "@/lib/modePreferences";
import { AUTO_HARNESS_ID, useBrainHarnessLabels } from "@/lib/agentLabels";
import { CLAUDE_NATIVE_MODELS } from "@/lib/claudeNativeModels";
import {
  isNativeHarnessPickerEntry,
  partitionAgentsByKind,
  sortAgentsForDisplay,
} from "@/lib/agentGrouping";
import { cn } from "@/lib/utils";
import {
  isNativeCodingAgent,
  nativeAgentHasCapability,
  nativeCodingAgentForAvailableAgent,
  nativeWrapperLabelsForAgent,
} from "@/lib/nativeCodingAgents";
import { useHostModelOptions, useHosts, type Host } from "@/hooks/useHosts";
import {
  useAvailableAgents,
  prefetchAvailableAgentDetails,
  type AvailableAgent,
} from "@/hooks/useAvailableAgents";
import { useAutoGrowTextarea } from "@/hooks/useAutoGrowTextarea";
import { useDictationInsert } from "@/hooks/useDictationInsert";
import { useHostFilesystem } from "@/hooks/useHostFilesystem";
import type { HostFilesystemEntry } from "@/hooks/useHostFilesystem";
import { useHostWorktrees } from "@/hooks/useHostWorktrees";
import { useNativeServerSwitcherForMainSurface } from "@/hooks/useNativeServerSwitcher";
import type { WorkspaceFile } from "@/hooks/useWorkspaceChangedFiles";
import type { Conversation } from "@/hooks/useConversations";
import type { NativeModelOption } from "@/lib/types";
import { useProjectConfig, useProjects, resolveOrCreateProjectId } from "@/hooks/useConversations";
import { projectQueryKeys } from "@/lib/projectQueries";
import { FileMentionMenu } from "@/components/FileMentionMenu";
import { useMentionBrowser } from "@/hooks/useMentionBrowser";
import {
  buildMentionPreamble,
  detectMentionAt,
  mentionItemPath,
  type MentionState,
  parseMentionToken,
  rankMentionEntries,
} from "@/lib/composerMentions";
import { OttoEyes } from "@/components/OttoEyes";
import { SkillPills } from "@/components/SkillPills";
import { ComposerMicButton } from "@/components/ComposerMicButton";
import type { CostControlMode } from "@/components/CostRoutingControl";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { AgentRowTooltip } from "@/components/AgentHoverCard";
import { CreateAgentDialog } from "./CreateAgentDialog";
import { buildAgentBundle, type AgentBundleInput } from "@/lib/agentBundle";
import { createBundledSession, launchRunner } from "@/lib/sessionsApi";

// Hidden from the new-session picker only. `nessie` is superseded by polly.
// `kimi` / `kimi-code` are the headless SDK harness (kept for sub-agent / `run
// --harness kimi` use) — the picker offers only the native TUI (`kimi-native-ui`).
const NEW_SESSION_HIDDEN_AGENTS = new Set(["nessie", "kimi", "kimi-code"]);

// Short picker-row blurbs — the spec descriptions are long paragraphs that
// truncate badly in the dropdown; other dialogs keep the server values.
const AGENT_PICKER_DESCRIPTIONS: Record<string, string> = {
  polly: "Multi-agent coding",
  debby: "Multi-agent debate",
};

// Agents whose bundled skills render as always-visible pills under the
// landing composer. Deliberately an allowlist while the pattern proves
// out — other agents keep the "/" menu as the only skill surface.
const SKILL_PILL_AGENTS = new Set(["polly", "debby"]);

// Claude Code's `claude --permission-mode` choices (v2.1). Claude-native
// sessions only. "default" is Claude's own default and sends no flag; any
// other value is passed through as `--permission-mode <value>` via the
// session's terminal_launch_args. Keep in sync with `claude --help`.
const CLAUDE_NATIVE_DEFAULT_PERMISSION_MODE = "default";
const CLAUDE_NATIVE_PERMISSION_MODES: { value: string; label: string; description: string }[] = [
  { value: "default", label: "Default", description: "Prompts before edits and commands" },
  {
    value: "auto",
    label: "Auto",
    description: "Auto-runs; a classifier blocks risky actions",
  },
  {
    value: "acceptEdits",
    label: "Accept edits",
    description: "Auto-applies file edits; commands still prompt",
  },
  { value: "plan", label: "Plan", description: "Plans only; makes no edits" },
  { value: "dontAsk", label: "Don't ask", description: "Auto-denies anything not pre-approved" },
  {
    value: "bypassPermissions",
    label: "Bypass permissions",
    description: "Runs everything; no prompts or safety checks",
  },
];

// Cursor execution modes. "default" sends no flags; other values map to CLI
// args passed via terminal_launch_args. Keep in sync with `cursor-agent --help`.
const CURSOR_NATIVE_DEFAULT_EXEC_MODE = "default";
const CURSOR_NATIVE_EXEC_MODES: {
  value: string;
  label: string;
  description: string;
  args: string[];
}[] = [
  {
    value: "default",
    label: "Default",
    description: "Normal agent mode; prompts before running commands",
    args: [],
  },
  {
    value: "auto-review",
    label: "Auto-review",
    description: "Smart Auto: auto-runs safe tool calls and prompts for the rest",
    args: ["--auto-review"],
  },
  {
    value: "plan",
    label: "Plan",
    description: "Read-only planning; analyzes and proposes plans, no edits",
    args: ["--mode", "plan"],
  },
  {
    value: "ask",
    label: "Ask",
    description: "Q&A style; explains and answers questions (read-only)",
    args: ["--mode", "ask"],
  },
  {
    value: "yolo",
    label: "Yolo",
    description: "Runs everything without prompts or safety checks",
    args: ["--yolo"],
  },
];

// Codex approval presets matching the `/permissions` TUI popup.
// Each preset bundles a sandbox profile + approval policy, mirroring
// codex-rs/utils/approval-presets/src/lib.rs. "default" is the auto
// preset (workspace-write + on-request) and sends no flags so the
// runner uses Codex's built-in default.
// Keep in sync with `codex --help` and
// https://developers.openai.com/codex/agent-approvals-security
const CODEX_NATIVE_DEFAULT_APPROVAL_MODE = "default";
const CODEX_NATIVE_APPROVAL_MODES: {
  value: string;
  label: string;
  description: string;
  args: string[];
}[] = [
  {
    value: "default",
    label: "Default",
    description: "Read/edit/run in workspace; approval for external edits or network",
    args: [],
  },
  {
    value: "full-access",
    label: "Full access",
    description: "Edit any file and access the internet without approval",
    args: ["--sandbox", "danger-full-access", "--ask-for-approval", "never"],
  },
  {
    value: "read-only",
    label: "Read only",
    description: "Read files only; approval required for edits, commands, or network",
    args: ["--sandbox", "read-only", "--ask-for-approval", "on-request"],
  },
];

// Conversation-label key for the DANGEROUS codex full-bypass opt-in. When
// set to "1" the runner launches Codex with
// `--dangerously-bypass-approvals-and-sandbox` (no approval prompts, no
// command sandbox) — see omnigent.stores.conversation_store
// CODEX_NATIVE_BYPASS_SANDBOX_LABEL_KEY. Stored as a label (cheap thread
// metadata) so it survives reload. Mutually exclusive in spirit with the
// approval-mode presets above: when bypass is on the runner strips any
// `--sandbox` / `--ask-for-approval` flags those presets would emit.
const CODEX_NATIVE_BYPASS_SANDBOX_LABEL_KEY = "omnigent.codex_native.bypass_sandbox";
// Bypass is the most-permissive Codex approval stance — presented as a 4th
// option in the Codex approval dropdown (Codex only; OpenCode shares the
// presets above but has no bypass). It rides as a conversation label, not
// terminal_launch_args, so its `args` are empty and it's handled specially.
const CODEX_NATIVE_BYPASS_APPROVAL_VALUE = "bypass";
const CODEX_NATIVE_BYPASS_APPROVAL_OPTION = {
  value: CODEX_NATIVE_BYPASS_APPROVAL_VALUE,
  label: "Bypass approvals & sandbox",
  description: "Runs Codex with no approval prompts and no command sandbox",
  args: [] as string[],
};

function displayModelId(option: Pick<NativeModelOption, "id">): string {
  return option.id;
}

function displayModelName(option: Pick<NativeModelOption, "id" | "displayName">): string {
  return option.displayName ?? option.id;
}

function defaultModelLabel(
  options: readonly Pick<NativeModelOption, "id" | "displayName" | "isDefault">[],
  display: (option: Pick<NativeModelOption, "id" | "displayName">) => string,
): string {
  const dflt = options.find((option) => option.isDefault);
  return dflt ? `Default (${display(dflt)})` : "Default";
}

export function ConnectHostInstructions({
  serverUrl,
  label,
}: {
  serverUrl: string;
  label?: string;
}) {
  // Databricks/internal deployments add the "Databricks Lakebox" connect
  // path; OSS deployments (where the lakebox launcher is excluded) show
  // only the plain `omni host` command. Driven by /v1/info.
  const info = useServerInfo();
  // "loading" before the boot probe resolves → treat as OSS (no Databricks
  // hints) until known, so the clean UI shows first and lakebox never flashes.
  const databricksFeatures = info !== "loading" && info.databricks_features;
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-dashed border-border p-4">
      {label && <p className="text-xs text-muted-foreground">{label}</p>}
      {databricksFeatures ? (
        <Tabs defaultValue="local">
          <TabsList className="w-full">
            <TabsTrigger value="local" className="text-xs">
              Local machine
            </TabsTrigger>
            <TabsTrigger value="lakebox" className="text-xs">
              Databricks Lakebox
            </TabsTrigger>
          </TabsList>
          <TabsContent value="local">
            <CliCommandBlock
              command={`omni host --server ${serverUrl}`}
              testIdPrefix="connect-host"
            />
          </TabsContent>
          <TabsContent value="lakebox" className="flex flex-col gap-1.5">
            <CliCommandBlock
              command="omni sandbox create --provider lakebox"
              testIdPrefix="connect-lakebox-create"
            />
            <CliCommandBlock
              command={`omni sandbox connect --provider lakebox --sandbox-id <id> --server ${serverUrl}`}
              testIdPrefix="connect-lakebox-connect"
            />
          </TabsContent>
        </Tabs>
      ) : (
        <CliCommandBlock command={`omni host --server ${serverUrl}`} testIdPrefix="connect-host" />
      )}
    </div>
  );
}

/**
 * Normalize a host filesystem path for equality comparison.
 *
 * Trims whitespace and strips trailing slashes so ``"/repo/"`` and
 * ``"/repo"`` compare equal, preserving the root ``"/"``. Blank/whitespace
 * input returns ``null`` (no path), never the root. Lexical only — no ``..``
 * or symlink resolution — which suffices because the server stores canonical
 * absolute workspaces, so a freshly typed absolute path matches directly.
 *
 * @param path A host path, e.g. ``"/Users/me/repo/"``.
 * @returns The normalized path, e.g. ``"/Users/me/repo"``; ``null`` for blank.
 */
export function normalizeWorkspacePath(path: string): string | null {
  const trimmed = path.trim();
  if (trimmed === "") return null;
  const stripped = trimmed.replace(/\/+$/, "");
  // All-slashes input (e.g. "///") collapses to the root.
  return stripped === "" ? "/" : stripped;
}

/**
 * Shorten an absolute path to its last two segments with a leading
 * ellipsis, so worktree rows show the disambiguating tail (e.g.
 * ``"…/myrepo-worktrees/feature-x"``) instead of a shared prefix that
 * truncates to the same string for every entry.
 *
 * @param path Absolute path, e.g. ``"/Users/me/myrepo-worktrees/feature-x"``.
 * @returns The tail, prefixed with ``"…/"`` when segments were dropped;
 *   the original path when it already has two or fewer segments.
 */
export function worktreePathTail(path: string): string {
  const segments = path.replace(/\/+$/, "").split("/").filter(Boolean);
  if (segments.length <= 2) return path;
  return `…/${segments.slice(-2).join("/")}`;
}

/**
 * Existing sessions that would share an on-disk working directory with a new
 * session created in ``workspace`` on ``hostId``.
 *
 * Matches on host plus normalized workspace path: a session whose stored
 * ``workspace`` equals the picked directory works in that same directory.
 * Branch sessions live in isolated worktree dirs (a different ``workspace``),
 * so they only match when the user explicitly picked that worktree path.
 *
 * Only *connected* sessions count — ``isRunnerOnline(s.id)`` must hold. An
 * offline or unbound session has no live process that could write the
 * directory, so it isn't a conflict. The caller backs this predicate with
 * the shared runner-health poll — the same ``/health`` signal as the
 * sidebar's connectivity dots — so the hint agrees with what the sidebar
 * shows.
 * Deleted sessions (≈ openui's archived) are already filtered out
 * server-side. An errored (``failed``) session whose runner is still online
 * counts, mirroring openui: only *disconnected* agents are excluded, not
 * merely errored ones.
 *
 * Returns ``[]`` when ``hostId`` is unset or ``workspace`` is blank.
 *
 * @param sessions The caller's sessions from ``useDirectorySessions``.
 * @param hostId The selected host id, or ``null`` when none is picked.
 * @param workspace The picked absolute directory, e.g. ``"/Users/me/repo"``.
 * @param isRunnerOnline Predicate: is this session's runner online right now?
 *   Backed by the shared runner-health poll in the component.
 * @returns Matching connected sessions; callers use ``.length`` for the count.
 */
export function sessionsSharingDirectory(
  sessions: Conversation[],
  hostId: string | null,
  workspace: string,
  isRunnerOnline: (sessionId: string) => boolean,
): Conversation[] {
  if (!hostId) return [];
  const target = normalizeWorkspacePath(workspace);
  if (target === null) return [];
  // TODO: headless agents (no `os_env`, no filesystem access) still get a
  // workspace via the web flow, so they count here — a false positive, since
  // they can't write. SessionListItem doesn't expose filesystem capability to
  // filter on; revisit (expose a flag + skip them) if headless agents with
  // working directories become common.
  return sessions.filter(
    (s) =>
      s.host_id === hostId &&
      s.workspace != null &&
      normalizeWorkspacePath(s.workspace) === target &&
      // Only a session whose runner is actually online has a live process
      // that could write here — same connectivity signal as the sidebar.
      isRunnerOnline(s.id),
  );
}

/** Return true for a fully-qualified absolute workspace path. */
export function isValidWorkspace(workspace: string): boolean {
  return workspace.trim().startsWith("/");
}

/**
 * Best-effort human-readable message for a failed POST /v1/sessions.
 *
 * Recognizes the OmnigentError shape (``{error: {message}}``) and
 * FastAPI's ``{detail}``; falls back to the status code otherwise.
 *
 * @param res Non-OK response from the session-create call.
 * @returns A message to show the user; falls back to the status code
 *   when the body isn't a recognizable error shape.
 */
export async function describeCreateError(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      // FastAPI HTTPException → {detail}; OpenResponses → {error:{message}}.
      const b = body as Record<string, unknown>;
      if (typeof b.detail === "string") return b.detail;
      if (
        Array.isArray(b.detail) &&
        b.detail.length > 0 &&
        typeof (b.detail[0] as Record<string, unknown>)?.msg === "string"
      ) {
        return (b.detail[0] as Record<string, unknown>).msg as string;
      }
      if (typeof b.message === "string") return b.message;
      const err = b.error;
      if (typeof err === "string") return err;
      if (
        err &&
        typeof err === "object" &&
        typeof (err as Record<string, unknown>).message === "string"
      ) {
        return (err as Record<string, unknown>).message as string;
      }
    }
  } catch {
    // Non-JSON body — fall through to the generic message.
  }
  return `Couldn't create the session (HTTP ${res.status}).`;
}

/**
 * The pre-feature "run omni setup" guidance (ReactNode), shown under the
 * composer when the UI-driven setup feature is OFF.
 *
 * The ``needs-auth`` / ``binary-missing`` copy is Codex-specific ("run codex
 * login" / "set OMNIGENT_CODEX_PATH"), so it's gated on {@link isCodexHarness}.
 * Other harnesses that report those structured reasons (claude-native /
 * opencode-native now do) fall through to the generic "run omni setup"
 * message — matching the pre-feature behavior, where only Codex ever produced
 * these reasons and everything else showed the generic text.
 */
function harnessWarningMessage(
  agentName: string | undefined,
  hostName: string | undefined,
  reason: string | null,
  harness: string | null | undefined,
): ReactNode {
  const isCodex = !!harness && isCodexHarness(harness);
  if (reason === "needs-auth" && isCodex) {
    return (
      <>
        {agentName} needs Codex authentication on {hostName} — run <code>codex login</code> on that
        machine.
      </>
    );
  }
  if (reason === "needs-auth" && !!harness && isNativeCursorHarness(harness)) {
    return (
      <>
        {agentName} needs Cursor login on {hostName} — run <code>cursor-agent login</code> on that
        machine.
      </>
    );
  }
  // ``version-too-low`` is a uniform state across all CLI harnesses now that
  // the server checks supported version ranges. Keep the message generic so
  // the user is nudged toward setup rather than being told the CLI is missing.
  if (reason === "version-too-low") {
    return (
      <>
        {agentName} has an outdated CLI on {hostName} — run <code>omni setup</code>, or upgrade the
        CLI directly on that machine.
      </>
    );
  }
  return (
    <>
      {agentName} isn&apos;t configured on {hostName} — run <code>omni setup</code> on that machine.
    </>
  );
}

/**
 * Amber "harness not ready on this host" notice under the composer, for the
 * currently-selected agent (case A: surfaced without opening the picker).
 *
 * Gated on the setup feature: when OFF, renders the original "run omnigent
 * setup" guidance so the flag-off UI is unchanged. When ON, offers a "Set up
 * <agent>" action that opens the shared {@link HarnessSetupDialog}.
 */
function HarnessSetupNotice({
  agentName,
  hostName,
  harness,
  reason,
  featureEnabled,
  onSetup,
}: {
  agentName: string | undefined;
  hostName: string | undefined;
  harness: string | null | undefined;
  reason: string | null;
  featureEnabled: boolean;
  onSetup: () => void;
}) {
  return (
    <p
      // pl-2 lines the icon up with the chips tray directly above (which has
      // pl-2), so the notice reads as part of the composer, not indented left.
      className="flex items-center gap-2 pl-2 text-xs text-amber-600 dark:text-amber-500"
      data-testid="new-chat-landing-harness-warning"
    >
      <TriangleAlertIcon className="size-3.5 shrink-0" />
      {featureEnabled ? (
        <>
          <span>
            {agentName} isn&apos;t ready on {hostName}.
          </span>
          {/* Compact bordered chip — small enough to sit on the sentence's line
              (h-5, text-xs), so it reads as part of the notice. */}
          <button
            type="button"
            data-testid="new-chat-landing-harness-setup"
            className="inline-flex h-5 shrink-0 items-center rounded-md border border-amber-300 px-2 text-xs font-medium text-amber-700 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 dark:border-amber-500/40 dark:text-amber-400 dark:hover:bg-amber-500/20"
            onClick={onSetup}
          >
            Set up {agentName}
          </button>
        </>
      ) : (
        <span>{harnessWarningMessage(agentName, hostName, reason, harness)}</span>
      )}
    </p>
  );
}

/**
 * Sanitize a user-typed initial prompt before it is sent.
 *
 * Strips C0/C1 control characters that could corrupt a terminal
 * agent's input when the runner injects the text via ``tmux
 * send-keys`` (Claude Code / Codex native), while preserving newlines
 * (``\n``) and tabs (``\t``) so multi-line prompts survive. Mirrors
 * openui's server-side terminal-input sanitization. Trailing/leading
 * whitespace is trimmed so a whitespace-only prompt collapses to "".
 *
 * @param prompt Raw textarea value the user typed, e.g.
 *   ``"read the README\nand summarize"``.
 * @returns The sanitized prompt; ``""`` when there's nothing to send.
 */
export function sanitizeInitialPrompt(prompt: string): string {
  // Intentional control-char class: strips C0 (\x00-\x1f) and C1
  // (\x7f-\x9f) ranges EXCEPT \t (\x09) and \n (\x0a), which multi-line
  // prompts need. The control chars in the class are the point of the
  // rule, so suppress no-control-regex here (oxlint honors this).
  // eslint-disable-next-line no-control-regex
  return prompt.replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f]/g, "").trim();
}

/**
 * Return true when ``url`` is acceptable as a sandbox repository URL.
 *
 * Mirrors the server's accepted forms (``parse_repo_workspace``):
 * ``https://<host>/<path>`` or scp-style ``git@<host>:<path>``. The
 * server is the authority — this only gates the submit button so an
 * obviously unusable value gets inline feedback instead of a 422.
 *
 * @param url Value the user typed in the repository input.
 * @returns true when ``url.trim()`` matches one of the two forms.
 */
export function isValidSandboxRepoUrl(url: string): boolean {
  const t = url.trim();
  return /^https:\/\/[^\s#/]+\/[^\s#]+$/.test(t) || /^git@[^\s#:]+:[^\s#]+$/.test(t);
}

/**
 * Compose the managed session's ``workspace`` string from the split
 * repository inputs.
 *
 * The API takes one Docker-build-context-style string —
 * ``<url>[#<branch>]`` — and the UI presents split fields, so this is
 * the reassembly step.
 *
 * @param url Repository URL input, e.g. ``"https://github.com/org/repo"``.
 * @param branch Branch input, e.g. ``"main"``; blank means the repo's
 *   default branch.
 * @returns The composed workspace string, or ``undefined`` when no
 *   repository was given (empty sandbox workspace).
 */
export function composeSandboxWorkspace(url: string, branch: string): string | undefined {
  const u = url.trim();
  if (u === "") return undefined;
  const b = branch.trim();
  return b === "" ? u : `${u}#${b}`;
}

/**
 * Derive a repository's display name from its URL.
 *
 * Last path segment with a trailing ``.git`` stripped — the same rule
 * the server uses for the clone directory, so the chip label matches
 * the workspace directory the session will get.
 *
 * @param url Repository URL, e.g. ``"https://github.com/org/repo.git"``.
 * @returns The name, e.g. ``"repo"``; ``null`` when underivable.
 */
export function deriveRepoName(url: string): string | null {
  const t = url.trim().replace(/\/+$/, "");
  if (t === "") return null;
  const last = t.split(/[/:]/).pop() ?? "";
  const name = last.endsWith(".git") ? last.slice(0, -4) : last;
  return name === "" ? null : name;
}

/**
 * Match a first message against an agent's bundled skills.
 *
 * Uses the in-session composer's shared command-shape guard
 * (:func:`isSlashCommandText`): the first token must read as ``/name``
 * (file paths like ``/etc/hosts`` never match), while the args after it
 * may carry anything — including paths and URLs, e.g.
 * ``"/review-pr https://github.com/..."``. The command name must
 * exactly match a bundled skill. Anything else — including
 * host-discovered skills the server can't know before a runner boots —
 * is sent as plain text, the same fall-through the in-session composer
 * uses for unknown commands.
 *
 * @param text The sanitized first message, e.g. ``"/review-pr 123"``.
 * @param skills The chosen agent's bundled skills from GET /v1/agents.
 * @returns The skill name and argument string, or ``null`` when the
 *   text is not an invocation of a bundled skill.
 */
export function matchSkillInvocation(
  text: string,
  skills: readonly { name: string }[],
): { name: string; args: string } | null {
  const trimmed = text.trim();
  if (!isSlashCommandText(trimmed)) return null;
  const command = trimmed.split(/\s+/)[0]!;
  const name = command.slice(1);
  if (!skills.some((s) => s.name === name)) return null;
  return { name, args: trimmed.slice(command.length).trim() };
}

/**
 * Derive a host home directory from one absolute child entry. Kept as a small
 * filesystem utility for consumers that still render a host directory picker;
 * the new-session screen no longer uses it to seed a Project workspace.
 */
export function deriveHomeDir(entries: HostFilesystemEntry[]): string | null {
  const first = entries[0];
  if (!first) return null;
  const slash = first.path.lastIndexOf("/");
  if (slash < 0) return null;
  return slash === 0 ? "/" : first.path.slice(0, slash);
}

/**
 * The home-page ("/") landing composer.
 *
 * Owns session creation end-to-end: the textarea is the first message and the
 * configuration chips (host, working directory, git worktree) plus the agent
 * picker supply every required parameter. Hitting send POSTs /v1/sessions and
 * navigates to the new session — there is no modal.
 */
/** Group / section header inside the picker dropdown (plain div, so Radix
 * doesn't claim roving focus for it — mirrors the in-session picker). */
function PickerSectionHeader({ children }: { children: ReactNode }) {
  return (
    <div className="px-2 pt-1.5 pb-0.5 text-[11px] font-medium text-muted-foreground">
      {children}
    </div>
  );
}

/**
 * Unified two-level agent/harness picker for the landing composer.
 *
 * **Level 1** groups every available agent under "Agents" (SDK / bundle
 * agents like Polly & Debby, plus custom user agents) and "Harnesses" (the
 * native terminal CLIs — Claude Code, Codex, Cursor, …). **Level 2** is a
 * per-entry submenu of that entry's run-config knobs: model / effort /
 * permission mode for Claude Code, approval mode (+ bypass) for Codex,
 * approval mode for OpenCode, execution mode for Cursor, and the brain-harness
 * override for bundle agents. Entries with no knobs are plain selectable rows.
 *
 * Holds no state of its own — the selected agent and every knob live in
 * {@link NewChatLandingScreen} and are threaded in. Replaces the old
 * left-side run-mode pills, the right-side model / harness controls, and the
 * footer-tray agent dropdown.
 *
 * Selecting a knob inside a not-yet-selected entry's submenu first selects
 * that entry (so the single shared knob state stays coherent), then applies
 * the value. For the mode knobs we persist the pick for the *entry's* harness
 * BEFORE selecting, so the harness-switch reseed effect in the screen reads it
 * back as the same value and doesn't clobber the choice.
 */
export function AgentHarnessPicker({
  agentEntries,
  harnessEntries,
  effectiveAgentId,
  agentLabel,
  hasAgents,
  host,
  onSelectAgent,
  pendingAgent,
  pendingAgentId,
  onSelectPending,
  onCreateCustomAgent,
  sandboxSelected,
  allowCreateCustomAgent = true,
  onOpenChange,
  dropdownModal = true,
  contentClassName,
  contentAlign = "end",
  triggerClassName,
  triggerLabelClassName,
}: {
  agentEntries: AvailableAgent[];
  harnessEntries: AvailableAgent[];
  effectiveAgentId: string | null;
  agentLabel: string;
  hasAgents: boolean;
  host: Host | undefined | null;
  onSelectAgent: (agent: AvailableAgent) => void;
  pendingAgent: AgentBundleInput | null;
  pendingAgentId: string;
  onSelectPending: () => void;
  onCreateCustomAgent: () => void;
  sandboxSelected: boolean;
  /** Whether to offer the "Create custom agent" action. Defaults true; an
   *  embedder that only picks an existing agent (e.g. project settings) can
   *  hide it since it has no interactive create flow. */
  allowCreateCustomAgent?: boolean;
  // ── Optional reuse hooks (all default-undefined) ─────────────────────────
  // These let a host OTHER than the composer footer embed the picker without
  // changing its default behavior. The interactive New Chat call site passes
  // none of them, so it renders exactly as before. The scheduled-task create
  // dialog passes them to: forward the dropdown open/close into its own
  // outside-click dismiss guard (`onOpenChange`), bound + left-align the menu
  // in a tall modal (`contentClassName` / `contentAlign`), and style the
  // trigger to match sibling <Select> fields (`triggerClassName` /
  // `triggerLabelClassName`).
  /** Notified when the picker dropdown opens/closes. */
  onOpenChange?: (open: boolean) => void;
  /** Whether the Radix dropdown should modal-block outside content. Defaults true. */
  dropdownModal?: boolean;
  /** Extra classes merged onto the dropdown content (e.g. a tighter max-h). */
  contentClassName?: string;
  /** Dropdown alignment. Defaults to "end" (composer footer). */
  contentAlign?: "start" | "center" | "end";
  /** Extra classes merged onto the trigger Button. */
  triggerClassName?: string;
  /** Extra classes merged onto the trigger's label span. */
  triggerLabelClassName?: string;
}) {
  const { t } = useTranslation("agents");
  // Controlled so picking a row can close the menu.
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const info = useServerInfo();
  // Feature ON → single "needs setup" badge; OFF → per-reason original text.
  const collapsedBadge = info !== "loading" && info.harness_install_enabled;
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Touch devices can't hover, so the desktop submenu flyouts ("More",
  // "Custom agents") are unreachable there. On mobile we swap the dropdown's
  // contents in place: tapping the row drills into that group's page (with a
  // Back row), instead of opening a hover flyout. `mobilePage` is the open
  // group (null = the main list); inert on desktop.
  const isMobile = useIsMobileViewport();
  const [mobilePage, setMobilePage] = useState<"more" | "custom" | null>(null);
  // Reset to the main list whenever the menu closes so it never reopens on a
  // stale drill-in page.
  useEffect(() => {
    if (!open) setMobilePage(null);
  }, [open]);

  // The agent name + optional short blurb, with the full spec description on
  // hover. Run-config knobs now live in the gear-icon config modal, not here —
  // this picker only selects the agent / harness.
  const renderRowInner = (agent: AvailableAgent, withTooltip: boolean) => {
    const blurb = AGENT_PICKER_DESCRIPTIONS[agent.name];
    const inner = (
      <div className="flex min-w-0 flex-1 items-baseline gap-2.5">
        <span className="truncate">{agent.display_name}</span>
        {blurb && <span className="truncate text-[11px] text-muted-foreground/70">{blurb}</span>}
      </div>
    );
    return withTooltip ? <AgentRowTooltip agent={agent}>{inner}</AgentRowTooltip> : inner;
  };

  const renderBadge = (agent: AvailableAgent) =>
    harnessUnconfiguredOnHost(agent.harness, host) ? (
      <Badge
        variant="outline"
        className="ml-auto self-center border-amber-300 bg-amber-50 text-[11px] text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400"
        data-testid={`new-chat-landing-agent-warning-${agent.id}`}
      >
        {harnessWarningBadgeText(
          harnessUnavailableReasonOnHost(agent.harness, host),
          collapsedBadge,
        )}
      </Badge>
    ) : null;

  // Each entry is a plain selectable row — selecting commits the pick and
  // closes the menu. Run-config knobs moved to the gear-icon config modal.
  const renderEntry = (agent: AvailableAgent): ReactNode => {
    const active = agent.id === effectiveAgentId;
    return (
      <DropdownMenuItem
        key={agent.id}
        data-testid={`new-chat-landing-agent-${agent.id}`}
        data-active={active ? "true" : undefined}
        onSelect={() => onSelectAgent(agent)}
        className="items-start gap-2 rounded-sm px-2 py-1.5 text-13 data-[active=true]:bg-accent/60 data-[active=true]:text-foreground"
      >
        {renderRowInner(agent, true)}
        {renderBadge(agent)}
      </DropdownMenuItem>
    );
  };

  // Opt-in "hide unconfigured harnesses" filter (Settings › Appearance). When
  // on, drop harness rows that can't launch on the selected host. Fails open:
  // harnessUnconfiguredOnHost returns false with no host / no readiness map, so
  // nothing is hidden in those cases, and unrecognized harnesses stay visible.
  const hideUnconfigured = useMemo(() => readHideUnconfiguredHarnesses(), []);
  // Split harnesses so the ready-to-use ones lead and the "needs setup" ones
  // fold into a "More" submenu (kept discoverable, out of the primary list).
  // The currently-selected harness always stays inline even when unconfigured,
  // so the active pick is never buried. With the hide-unconfigured preference
  // on, unconfigured harnesses are dropped entirely (no "More").
  const { readyHarnessEntries, moreHarnessEntries } = useMemo(() => {
    const ready: AvailableAgent[] = [];
    const more: AvailableAgent[] = [];
    const targetReadinessUnknown = host == null;
    for (const a of harnessEntries) {
      const unconfigured = harnessUnconfiguredOnHost(a.harness, host);
      if (a.id === effectiveAgentId || (!unconfigured && !targetReadinessUnknown)) ready.push(a);
      else if (targetReadinessUnknown || !hideUnconfigured) more.push(a);
    }
    return { readyHarnessEntries: ready, moreHarnessEntries: more };
  }, [harnessEntries, host, hideUnconfigured, effectiveAgentId]);

  // Split the agents group: built-in bundle agents (Polly / Debby) stay inline
  // in the main list; user-registered custom agents fold into a "Custom agents"
  // submenu so a long roster doesn't crowd out the recommended picks.
  const { builtins: bundleEntries, customs: customEntries } = useMemo(
    () => partitionAgentsByKind(agentEntries),
    [agentEntries],
  );

  // Existing custom / pending agents fold into a "Custom agents" submenu so a
  // long roster doesn't crowd the recommended picks. When there are none, the
  // submenu would hold only the create action — which is a poor place to
  // discover it — so we surface "Create custom agent" as a top-level row
  // instead (see below). The submenu therefore renders only when there is at
  // least one custom / pending agent to group.
  const hasCustomAgents = customEntries.length > 0 || pendingAgent != null;
  // "Create custom agent" is reachable on any non-sandbox target (a managed
  // sandbox has no create path for an uploaded bundle), unless the embedder
  // opts out (it has no create flow to route the action to).
  const canCreateAgent = !sandboxSelected && allowCreateCustomAgent;
  const createAgentItem = canCreateAgent ? (
    <DropdownMenuItem
      data-testid="new-chat-landing-create-agent"
      onSelect={onCreateCustomAgent}
      className="gap-2 rounded-sm px-2 py-1.5 text-13 text-muted-foreground"
    >
      <PlusIcon className="size-3.5" />
      {t("picker.createCustom")}
    </DropdownMenuItem>
  ) : null;
  const hasCustomGroup = hasCustomAgents;
  // Shared body for the custom-agents submenu (desktop flyout + mobile page):
  // the custom agents, the pending upload, and the create action.
  const customAgentsBody = (
    <>
      {customEntries.map(renderEntry)}
      {pendingAgent && (
        <DropdownMenuItem
          key={pendingAgentId}
          data-testid="new-chat-landing-agent-pending"
          data-active={effectiveAgentId === pendingAgentId ? "true" : undefined}
          onSelect={onSelectPending}
          className="items-start gap-2 rounded-sm px-2 py-1.5 text-13 data-[active=true]:bg-accent/60 data-[active=true]:text-foreground"
        >
          <div className="flex min-w-0 flex-1 items-baseline gap-2.5">
            <span className="truncate">{pendingAgent.name}</span>
            <span className="truncate text-[11px] text-muted-foreground/70">
              {t("picker.custom")}
            </span>
          </div>
        </DropdownMenuItem>
      )}
      {canCreateAgent && (
        <>
          <DropdownMenuSeparator />
          {createAgentItem}
        </>
      )}
    </>
  );
  // Which mobile drill-in page is showing (gated so a group that vanished — e.g.
  // list refresh — can't strand the menu on an empty page).
  const showMore = isMobile && mobilePage === "more" && moreHarnessEntries.length > 0;
  const showCustom = isMobile && mobilePage === "custom" && hasCustomGroup;
  // If the open page's group disappears (or the viewport grows to desktop),
  // fall back to the main list so a reopened menu never lands on an empty page.
  useEffect(() => {
    if (mobilePage === "more" && !showMore) setMobilePage(null);
    if (mobilePage === "custom" && !showCustom) setMobilePage(null);
  }, [mobilePage, showMore, showCustom]);

  return (
    <DropdownMenu
      modal={dropdownModal}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        onOpenChange?.(next);
        if (next) {
          // Prefetch harness/description/skills for all session-discovered
          // agents so the list is stable before the user reads it.
          for (const agent of [...harnessEntries, ...agentEntries]) {
            void prefetchAvailableAgentDetails(agent, queryClient);
          }
        }
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button
          ref={triggerRef}
          type="button"
          variant="ghost"
          size="sm"
          disabled={!hasAgents}
          data-testid="new-chat-landing-agent-select"
          // Drop the Button's focus-visible ring/border that otherwise shows
          // when focus returns to the trigger after a pick. `triggerClassName`
          // (default undefined) lets an embedder override sizing/border to match
          // its own form fields; tailwind-merge lets the passed classes win.
          className={cn(
            "h-8 gap-1.5 pr-1 pl-2.5 font-normal text-muted-foreground hover:text-foreground focus-visible:border-transparent focus-visible:ring-0",
            triggerClassName,
          )}
        >
          <span
            className={cn("max-w-[12rem] truncate text-xs text-foreground", triggerLabelClassName)}
          >
            {hasAgents ? agentLabel : t("picker.noAgents")}
          </span>
          <ChevronDownIcon className="size-3.5 opacity-60" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={contentAlign}
        // Keep the menu inside the viewport on short mobile screens: pad the
        // collision box so the available-height cap leaves room below the
        // status bar, and let it flip/scroll rather than run off the top.
        collisionPadding={12}
        avoidCollisions
        // `contentClassName` (default undefined) lets an embedder tighten the
        // height cap / pin a width; tailwind-merge lets the passed max-h/width
        // override the defaults.
        className={cn(
          "max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-64 max-w-[calc(100vw-2rem)] overflow-y-auto p-1",
          contentClassName,
        )}
      >
        {showMore ? (
          // Mobile drill-in page for the "needs setup" harnesses.
          <div className="animate-in fade-in-0 slide-in-from-right-2 duration-150">
            <DropdownMenuItem
              data-testid="new-chat-landing-page-back"
              onSelect={(e) => {
                e.preventDefault();
                setMobilePage(null);
              }}
              className="items-center gap-1.5 rounded-sm px-2 py-1.5 text-13 font-medium"
            >
              <ChevronLeftIcon className="size-4 shrink-0 opacity-70" />
              <span className="truncate">{t("picker.more")}</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {moreHarnessEntries.map(renderEntry)}
          </div>
        ) : showCustom ? (
          // Mobile drill-in page for custom agents.
          <div className="animate-in fade-in-0 slide-in-from-right-2 duration-150">
            <DropdownMenuItem
              data-testid="new-chat-landing-page-back"
              onSelect={(e) => {
                e.preventDefault();
                setMobilePage(null);
              }}
              className="items-center gap-1.5 rounded-sm px-2 py-1.5 text-13 font-medium"
            >
              <ChevronLeftIcon className="size-4 shrink-0 opacity-70" />
              <span className="truncate">{t("picker.customAgents")}</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {customAgentsBody}
          </div>
        ) : (
          <>
            {/* Harnesses group first — the native terminal CLIs (Claude Code is
            the default), so the most-used picks lead. Ready-to-use harnesses
            list inline; "needs setup" ones fold into a "More" group. */}
            {(readyHarnessEntries.length > 0 || moreHarnessEntries.length > 0) && (
              <>
                <PickerSectionHeader>{t("picker.harnesses")}</PickerSectionHeader>
                {readyHarnessEntries.map(renderEntry)}
                {moreHarnessEntries.length > 0 &&
                  (isMobile ? (
                    // Touch: drill into a "More" page in place (with Back).
                    <DropdownMenuItem
                      data-testid="new-chat-landing-harness-more"
                      onSelect={(e) => {
                        e.preventDefault();
                        setMobilePage("more");
                      }}
                      className="items-center gap-2 rounded-sm px-2 py-1.5 text-13"
                    >
                      <span className="flex-1">{t("picker.more")}</span>
                      <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground/70" />
                    </DropdownMenuItem>
                  ) : (
                    // Desktop: hover flyout submenu.
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger
                        data-testid="new-chat-landing-harness-more"
                        className="items-center gap-2 rounded-sm px-2 py-1.5 text-13"
                      >
                        <span className="flex-1">{t("picker.more")}</span>
                      </DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-56 max-w-[calc(100vw-2rem)] overflow-y-auto p-1">
                        {moreHarnessEntries.map(renderEntry)}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                  ))}
                <DropdownMenuSeparator />
              </>
            )}
            {/* Agents group — built-in bundle agents (Polly / Debby) inline. */}
            <PickerSectionHeader>{t("picker.agents")}</PickerSectionHeader>
            {bundleEntries.map(renderEntry)}
            {/* Existing custom agents fold into a "Custom agents" submenu (with
            the pending upload and the create action). With no custom agents the
            submenu would hold only "Create custom agent", so we surface that as
            a top-level row instead — otherwise creation is invisible on a fresh
            server. A managed sandbox has no create path, so neither appears. */}
            {hasCustomGroup &&
              (isMobile ? (
                // Touch: drill into a "Custom agents" page in place (with Back).
                <DropdownMenuItem
                  data-testid="new-chat-landing-custom-agents"
                  onSelect={(e) => {
                    e.preventDefault();
                    setMobilePage("custom");
                  }}
                  className="items-center gap-2 rounded-sm px-2 py-1.5 text-13"
                >
                  <span className="flex-1">{t("picker.customAgents")}</span>
                  <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground/70" />
                </DropdownMenuItem>
              ) : (
                // Desktop: hover flyout submenu.
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger
                    data-testid="new-chat-landing-custom-agents"
                    className="items-center gap-2 rounded-sm px-2 py-1.5 text-13"
                  >
                    <span className="flex-1">{t("picker.customAgents")}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="max-h-[var(--radix-dropdown-menu-content-available-height)] min-w-56 max-w-[calc(100vw-2rem)] overflow-y-auto p-1">
                    {customAgentsBody}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              ))}
            {/* No custom agents to group: surface the create action directly so
            it stays discoverable instead of hiding behind an empty submenu. */}
            {!hasCustomGroup && createAgentItem}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Harness-configuration modal opened from the composer's gear icon. Shows the
 * selected agent's run-config knobs — Claude: model / effort / permissions;
 * Codex/OpenCode: approval mode (+ Codex's dangerous full-bypass opt-in);
 * Cursor: exec mode; bundle agents: brain-harness override.
 *
 * The modal edits a LOCAL draft seeded from the live state each time it opens,
 * and only commits to the parent state + per-harness persistence on Save;
 * Cancel / dismiss discards. This is the deliberate Save/Cancel UX (the old
 * in-dropdown submenu committed on every change).
 */
function HarnessConfigModal({
  open,
  onOpenChange,
  agent,
  brainHarnessLabels,
  host,
  hideUnconfigured,
  smartRoutingEligible,
  permissionMode,
  approvalMode,
  cursorExecMode,
  bypassSandbox,
  pickedModel,
  claudeModelOptions,
  claudeModelsLoading,
  codexModelOptions,
  codexModelsLoading,
  pickedEffort,
  pickedHarness,
  costControlMode,
  setPermissionMode,
  setApprovalMode,
  setCursorExecMode,
  setBypassSandbox,
  setPickedModel,
  setPickedEffort,
  setPickedHarness,
  setCostControlMode,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent: AvailableAgent;
  brainHarnessLabels: Record<string, string>;
  host: Host | undefined | null;
  hideUnconfigured: boolean;
  smartRoutingEligible: boolean;
  permissionMode: string;
  approvalMode: string;
  cursorExecMode: string;
  bypassSandbox: boolean;
  pickedModel: string;
  claudeModelOptions: readonly Pick<NativeModelOption, "id" | "displayName" | "isDefault">[];
  claudeModelsLoading: boolean;
  codexModelOptions: readonly Pick<NativeModelOption, "id" | "displayName" | "isDefault">[];
  codexModelsLoading: boolean;
  pickedEffort: string;
  pickedHarness: string | null;
  costControlMode: CostControlMode;
  setPermissionMode: (mode: string) => void;
  setApprovalMode: (mode: string) => void;
  setCursorExecMode: (mode: string) => void;
  setBypassSandbox: (enabled: boolean) => void;
  setPickedModel: (model: string) => void;
  setPickedEffort: (effort: string) => void;
  setPickedHarness: (harness: string | null, agentId?: string) => void;
  setCostControlMode: (mode: CostControlMode) => void;
}) {
  const { t } = useTranslation("models");
  const info = useServerInfo();
  // Feature ON → single "needs setup" badge; OFF → per-reason original text.
  const collapsedBadge = info !== "loading" && info.harness_install_enabled;
  const entryHarness = nativeCodingAgentForAvailableAgent(agent)?.harness ?? null;
  const hasPermission = nativeAgentHasCapability(agent, "permissionMode");
  const hasApproval = nativeAgentHasCapability(agent, "approvalMode");
  const hasCursor = nativeAgentHasCapability(agent, "cursorMode");
  const isCodex = entryHarness === "codex-native";
  const modelOptions = isCodex ? codexModelOptions : claudeModelOptions;
  const modelsLoading = isCodex ? codexModelsLoading : claudeModelsLoading;
  const modelDisplay = isCodex ? displayModelId : displayModelName;
  const brainDefault =
    agent.harness != null && agent.harness in brainHarnessLabels ? agent.harness : null;

  // Local draft — seeded from the live state each time the modal opens so
  // Cancel can discard and re-opening always reflects the committed state.
  const [draftModel, setDraftModel] = useState(pickedModel);
  const [draftEffort, setDraftEffort] = useState(pickedEffort);
  const [draftPermission, setDraftPermission] = useState(permissionMode);
  const [draftApproval, setDraftApproval] = useState(approvalMode);
  const [draftCursor, setDraftCursor] = useState(cursorExecMode);
  const [draftBypass, setDraftBypass] = useState(bypassSandbox);
  const [draftHarness, setDraftHarness] = useState<string | null>(pickedHarness);
  const [draftRouting, setDraftRouting] = useState<CostControlMode>(costControlMode);

  useEffect(() => {
    if (!open) return;
    setDraftModel(pickedModel);
    setDraftEffort(pickedEffort);
    setDraftPermission(permissionMode);
    setDraftApproval(approvalMode);
    setDraftCursor(cursorExecMode);
    setDraftBypass(bypassSandbox);
    setDraftHarness(pickedHarness);
    setDraftRouting(costControlMode);
    // Seed once per open from the current live values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Only treat routing as "on" when it's actually offered for this agent —
  // otherwise a stale costControlMode="on" (e.g. server later disabled the
  // flag) would select the __smart__ sentinel with no matching Select item.
  const smartRoutingOn = smartRoutingEligible && draftRouting === "on";
  const modelValue = smartRoutingOn ? MODEL_SELECT_SMART : draftModel || MODEL_SELECT_DEFAULT;
  const onModelChange = (value: string) => {
    if (value === MODEL_SELECT_SMART) {
      setDraftRouting("on");
      setDraftModel("");
      // The router picks the model (and its effort) per turn, so an explicit
      // effort is meaningless — reset it so it doesn't ride along frozen.
      setDraftEffort("");
    } else if (value === MODEL_SELECT_DEFAULT) {
      setDraftModel("");
      // "Default" = no override; defer routing to the spec default (null,
      // omitted from create) — never emit an explicit "on"/"off".
      setDraftRouting(null);
    } else {
      setDraftModel(value);
      // Picking an explicit model turns routing off (mutually exclusive).
      setDraftRouting(null);
    }
  };

  const save = () => {
    if (hasPermission) {
      // Order matters: commit model first (its setter clears routing when a
      // model is set), then routing (its setter clears the model when "on") —
      // the two setters enforce the mutual exclusion between them.
      setPickedModel(draftModel);
      setPickedEffort(draftEffort);
      setPermissionMode(draftPermission);
      if (entryHarness)
        writeHarnessOption(entryHarness, {
          model: draftModel,
          effort: draftEffort,
          mode: draftPermission,
        });
    } else if (hasApproval) {
      if (isCodex) setPickedModel(draftModel);
      setApprovalMode(draftApproval);
      setBypassSandbox(draftBypass);
      if (entryHarness)
        writeHarnessOption(entryHarness, {
          mode: draftApproval,
          ...(isCodex ? { model: draftModel } : {}),
        });
    } else if (hasCursor) {
      setCursorExecMode(draftCursor);
      if (entryHarness) writeHarnessOption(entryHarness, { mode: draftCursor });
    } else if (brainDefault) {
      // Picking the spec default clears the override so the session tracks it.
      setPickedHarness(draftHarness === brainDefault ? null : draftHarness, agent.id);
    }
    // Smart Routing is offered on Claude (Model dropdown) and other routable
    // agents (standalone toggle), so commit it for every eligible agent — not
    // just the Claude branch above.
    if (smartRoutingEligible) setCostControlMode(draftRouting);
    onOpenChange(false);
  };

  const brainEntries = brainDefault
    ? Object.entries(brainHarnessLabels).filter(
        ([id]) =>
          id === (draftHarness ?? brainDefault) ||
          !hideUnconfigured ||
          !harnessUnconfiguredOnHost(id, host),
      )
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="new-chat-landing-config-modal">
        <DialogHeader>
          <DialogTitle>{t("configure", { name: agent.display_name })}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("newSessionDescription", { name: agent.display_name })}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-1">
          {/* Smart Routing as a standalone toggle, first, for routable agents
          that have no Model dropdown to fold it into (Codex, bundle agents, …).
          Claude offers it as a Model option instead, so it's excluded here. */}
          {smartRoutingEligible && !hasPermission && (
            <ConfigRow label={t("smartRouting")} description={t("autoPick")}>
              <div className="flex h-8 items-center justify-end">
                <Switch
                  size="sm"
                  checked={smartRoutingOn}
                  data-testid="new-chat-landing-config-smart-routing"
                  aria-label={t("smartRoutingAria")}
                  onCheckedChange={(next) => setDraftRouting(next ? "on" : "off")}
                />
              </div>
            </ConfigRow>
          )}
          {hasPermission && (
            <>
              <ConfigRow label={t("model")} description={t("underlyingLlm")}>
                <Select value={modelValue} onValueChange={onModelChange}>
                  <SelectTrigger
                    className="w-full"
                    data-testid="new-chat-landing-config-model"
                    aria-label={t("model")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent
                    position="popper"
                    align="start"
                    className="[&_[data-slot=select-item]]:pl-2.5"
                  >
                    {smartRoutingEligible && (
                      <SelectItem value={MODEL_SELECT_SMART}>{t("smartRouting")}</SelectItem>
                    )}
                    <SelectItem value={MODEL_SELECT_DEFAULT}>{t("reasoning.default")}</SelectItem>
                    {claudeModelOptions.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.displayName}
                      </SelectItem>
                    ))}
                    {claudeModelsLoading && (
                      <div className="px-2.5 py-1 text-xs text-muted-foreground">
                        {t("loadingModels")}
                      </div>
                    )}
                    {!claudeModelsLoading && claudeModelOptions.length === 0 && (
                      <div className="px-2.5 py-1 text-xs text-muted-foreground">
                        {t("modelsUnavailable")}
                      </div>
                    )}
                  </SelectContent>
                </Select>
              </ConfigRow>

              <ConfigRow label={t("effort")} description={t("reasoningDepth")}>
                <Select
                  value={draftEffort || EFFORT_SELECT_NONE}
                  onValueChange={(v) => setDraftEffort(v === EFFORT_SELECT_NONE ? "" : v)}
                  // Smart Routing picks the model + effort per turn, so an
                  // explicit effort can't apply — freeze it to Default.
                  disabled={smartRoutingOn}
                >
                  <SelectTrigger
                    className="w-full"
                    data-testid="new-chat-landing-config-effort"
                    aria-label={t("effort")}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent
                    position="popper"
                    align="start"
                    className="[&_[data-slot=select-item]]:pl-2.5"
                  >
                    <SelectItem value={EFFORT_SELECT_NONE}>{t("reasoning.default")}</SelectItem>
                    {CLAUDE_NATIVE_EFFORTS.map((e) => (
                      <SelectItem key={e.value} value={e.value}>
                        {translateConfigOptionLabel(t, e.value, e.label)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>

              <ConfigRow label={t("permissions")} description={t("permissionsDescription")}>
                <DescribedSelect
                  value={draftPermission}
                  onValueChange={setDraftPermission}
                  options={CLAUDE_NATIVE_PERMISSION_MODES}
                  testId="new-chat-landing-config-permission"
                  ariaLabel={t("permissions")}
                />
              </ConfigRow>
            </>
          )}

          {hasApproval && isCodex && (
            <ConfigRow label={t("model")} description={t("underlyingLlm")}>
              <Select value={modelValue} onValueChange={onModelChange}>
                <SelectTrigger
                  className="w-full"
                  data-testid="new-chat-landing-config-model"
                  aria-label={t("model")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  position="popper"
                  align="start"
                  className="[&_[data-slot=select-item]]:pl-2.5"
                >
                  <SelectItem value={MODEL_SELECT_DEFAULT}>
                    {defaultModelLabel(modelOptions, modelDisplay).replace(
                      /^Default/,
                      t("reasoning.default"),
                    )}
                  </SelectItem>
                  {modelOptions.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {displayModelId(m)}
                    </SelectItem>
                  ))}
                  {modelsLoading && (
                    <div className="px-2.5 py-1 text-xs text-muted-foreground">
                      {t("loadingModels")}
                    </div>
                  )}
                  {!modelsLoading && modelOptions.length === 0 && (
                    <div className="px-2.5 py-1 text-xs text-muted-foreground">
                      {t("modelsUnavailable")}
                    </div>
                  )}
                </SelectContent>
              </Select>
            </ConfigRow>
          )}

          {hasApproval && (
            <>
              <ConfigRow label={t("approval")} description={t("approvalDescription")}>
                <DescribedSelect
                  // Codex adds the DANGEROUS full-bypass as a 4th option; when
                  // armed the select shows it (draftBypass wins over the preset).
                  value={
                    isCodex && draftBypass ? CODEX_NATIVE_BYPASS_APPROVAL_VALUE : draftApproval
                  }
                  onValueChange={(v) => {
                    if (v === CODEX_NATIVE_BYPASS_APPROVAL_VALUE) {
                      setDraftBypass(true);
                    } else {
                      setDraftBypass(false);
                      setDraftApproval(v);
                    }
                  }}
                  options={
                    isCodex
                      ? [...CODEX_NATIVE_APPROVAL_MODES, CODEX_NATIVE_BYPASS_APPROVAL_OPTION]
                      : CODEX_NATIVE_APPROVAL_MODES
                  }
                  testId="new-chat-landing-config-approval"
                  ariaLabel={t("approval")}
                />
              </ConfigRow>
              {/* Persistent danger banner while full-bypass is selected. */}
              {isCodex && draftBypass && (
                <div
                  role="alert"
                  data-testid="new-chat-landing-bypass-sandbox-banner"
                  className="flex items-start gap-1.5 rounded-md border border-destructive bg-destructive/10 px-2 py-1.5 text-xs font-medium leading-relaxed text-destructive"
                >
                  <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                  <span>{t("dangerBypass")}</span>
                </div>
              )}
            </>
          )}

          {hasCursor && (
            <ConfigRow label={t("mode")} description={t("modeDescription")}>
              <DescribedSelect
                value={draftCursor}
                onValueChange={setDraftCursor}
                options={CURSOR_NATIVE_EXEC_MODES}
                testId="new-chat-landing-config-cursor-mode"
                ariaLabel={t("mode")}
              />
            </ConfigRow>
          )}

          {!hasPermission && !hasApproval && !hasCursor && brainDefault && (
            <ConfigRow label={t("harness")} description={t("harnessDescription")}>
              <Select value={draftHarness ?? brainDefault} onValueChange={setDraftHarness}>
                <SelectTrigger
                  className="w-full"
                  data-testid="new-chat-landing-config-harness"
                  aria-label={t("harness")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  position="popper"
                  align="start"
                  className="[&_[data-slot=select-item]]:pl-2.5"
                >
                  {brainEntries.map(([id, label]) => (
                    <SelectItem key={id} value={id} data-testid={`new-chat-landing-harness-${id}`}>
                      <span className="flex items-center gap-2">
                        {label}
                        {harnessUnconfiguredOnHost(id, host) && (
                          <Badge
                            variant="outline"
                            className="border-amber-300 bg-amber-50 text-[11px] text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400"
                            data-testid={`new-chat-landing-harness-warning-${id}`}
                          >
                            {harnessWarningBadgeText(
                              harnessUnavailableReasonOnHost(id, host),
                              collapsedBadge,
                            )}
                          </Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </ConfigRow>
          )}
        </div>

        <DialogFooter className="border-t-0 bg-transparent">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="new-chat-landing-config-cancel"
          >
            {t("cancel")}
          </Button>
          <Button type="button" onClick={save} data-testid="new-chat-landing-config-save">
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// In-memory draft for the new-session landing screen, so a half-composed
// message, attachments and picker selections survive the unmount that happens
// when the user navigates into an existing session and back. Module-scoped,
// not persisted to storage (a page refresh starts clean); cleared on create.
interface LandingDraft {
  message: string;
  files: File[];
  pickedAgentId: string | null;
  selectedHostId: string | null;
  sandboxSelected: boolean;
  workspace: string;
  branchName: string;
  prefilledBranch: string;
  permissionMode: string;
  approvalMode: string;
  bypassSandbox: boolean;
  cursorExecMode: string;
  pickedHarness: string | null;
  pickedModel: string;
  pickedEffort: string;
  costControlMode: CostControlMode;
}

let landingDraft: LandingDraft | null = null;

// Test-only: clears the preserved landing draft so each case starts from a
// clean module state (the draft is module-scoped and survives unmount by
// design, which would otherwise leak between tests).
export function resetLandingDraft(): void {
  landingDraft = null;
}

export function NewChatLandingScreen() {
  const { t } = useTranslation("models");
  const { t: commonT } = useTranslation("common");
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { data: agents } = useAvailableAgents();
  // refetchOnFocus: returning from a terminal `omni setup` must clear the
  // readiness badge even if the live push was missed while the tab was hidden.
  const { data: hosts, isLoading: hostsLoading } = useHosts({ refetchOnFocus: true });

  const agentList = useMemo(
    () =>
      sortAgentsForDisplay((agents ?? []).filter((a) => !NEW_SESSION_HIDDEN_AGENTS.has(a.name))),
    [agents],
  );

  // Split canonical native CLI entries from SDK and custom bundle agents.
  // A bundle may use a native harness without becoming a runtime entry.
  const harnessEntries = useMemo(
    () => agentList.filter((a) => isNativeHarnessPickerEntry(a)),
    [agentList],
  );
  const agentEntries = useMemo(
    () => agentList.filter((a) => !isNativeHarnessPickerEntry(a)),
    [agentList],
  );

  // "Create custom agent" dialog state and pending bundle. When the user
  // creates a custom agent via the dialog, the bundle input is stored
  // here and the picker switches to a virtual "pending" agent entry. On
  // form submit, handleCreate detects the pending bundle, builds the
  // tar.gz, and uses multipart POST instead of the normal JSON path.
  const [createAgentOpen, setCreateAgentOpen] = useState(false);
  const [pendingAgent, setPendingAgent] = useState<AgentBundleInput | null>(null);
  // Sentinel id for the pending custom agent in the picker dropdown.
  const PENDING_AGENT_ID = "__pending_custom_agent__";

  // Surface element backing the iOS native server switcher overlay, which
  // the in-session view shows too — the picker stays reachable while starting
  // a new session. The hook hides it whenever the sidebar covers the surface.
  const [landingSurface, setLandingSurface] = useState<HTMLElement | null>(null);
  useNativeServerSwitcherForMainSurface(landingSurface, true);

  const [message, setMessage] = useState<string>(() => landingDraft?.message ?? "");
  const dictation = useDictationInsert(setMessage);
  // Composer text captured when voice dictation starts, so Esc can revert to it.
  const voiceSnapshotRef = useRef("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);
  // maxRows 9 = 180px of 20px lines, matching the composer's 200px
  // border-box max (180px content + 16px top / 4px bottom padding).
  useAutoGrowTextarea(textareaRef, message, 9);

  // Attachments for the first message — same affordances as the in-session
  // composer (paperclip + paste); carried to ChatPage via the pending
  // initial prompt and sent with the auto-dispatched first turn.
  const [files, setFiles] = useState<File[]>(() => landingDraft?.files ?? []);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const addFiles = (incoming: File[]) => setFiles((prev) => [...prev, ...incoming]);
  const removeFile = (index: number) => setFiles((prev) => prev.filter((_, i) => i !== index));

  // Drag-and-drop onto the composer — same behavior as the in-session
  // composer (drop files anywhere on the box; an inset ring + overlay
  // signal the drop target).
  const [isDragActive, setIsDragActive] = useState(false);

  const handleDrop = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length > 0) addFiles(dropped);
  };

  const handleDragOver = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(true);
  };

  const handleDragEnter = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    // Only clear the active state when the pointer leaves the container
    // itself, not when it moves between child elements inside it.
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragActive(false);
  };

  // Gates the sandbox host option: only servers whose sandbox
  // config can actually serve a managed launch advertise it. "loading"
  // fails closed (option hidden) until the boot probe resolves.
  const info = useServerInfo();
  const managedSandboxesEnabled = info !== "loading" && info.managed_sandboxes_enabled;
  const smartRoutingEnabled = info !== "loading" && info.smart_routing_enabled;
  // Gates the whole UI-driven setup experience (Set up affordance + dialog +
  // collapsed badge). OFF → the composer/picker fall back to the original
  // "run omni setup" guidance, so a disabled flag is a no-op on the UI.
  const harnessInstallEnabled = info !== "loading" && info.harness_install_enabled;
  const brainHarnessLabels = useBrainHarnessLabels(smartRoutingEnabled);
  // Provider-named label for the sandbox option (e.g. "Modal Sandbox"),
  // falling back to the generic "New Sandbox" when the server names no
  // provider.
  const sandboxLabel = sandboxOptionLabel(info !== "loading" ? info.sandbox_provider : null);

  // Project driving this visit, when the sidebar's per-project "new session"
  // pencil landed here with a `?project=` query param. Empty otherwise.
  const projectParam = searchParams.get("project") ?? "";
  // Seeded from the persisted last pick so a returning user starts on the
  // agent they used last; validated against the live list in
  // effectiveAgentId below (a stale id falls back to the default). A
  // project-driven visit defers to the project-prefill effect instead
  // (which falls back to the same last pick).
  const [pickedAgentId, setPickedAgentId] = useState<string | null>(() =>
    projectParam === "" ? (landingDraft?.pickedAgentId ?? readLastAgentId()) : null,
  );
  const [selectedHostId, setSelectedHostId] = useState<string | null>(() =>
    projectParam === "" ? (landingDraft?.selectedHostId ?? null) : null,
  );
  // Sessions on the selected host — fetched only when a host is selected,
  // to avoid registering hundreds of sessions into the health poll at idle.
  // True when the user picked the sandbox option instead of a connected
  // host — the server provisions a sandbox host at create time
  // (host_type: "managed"), so no host_id or workspace is sent.
  const [sandboxSelected, setSandboxSelected] = useState(() =>
    projectParam === "" ? (landingDraft?.sandboxSelected ?? false) : false,
  );
  const { data: hostClaudeModelOptions, isLoading: hostClaudeModelsLoading } = useHostModelOptions(
    selectedHostId,
    "claude-native",
    !sandboxSelected,
  );
  const { data: hostCodexModelOptions, isLoading: hostCodexModelsLoading } = useHostModelOptions(
    selectedHostId,
    "codex-native",
    !sandboxSelected,
  );
  const claudeModelOptions = useMemo(
    () =>
      sandboxSelected
        ? CLAUDE_NATIVE_MODELS.map((model) => ({
            id: model.id,
            displayName: model.label,
          }))
        : (hostClaudeModelOptions ?? []).map((option) => ({
            id: option.id,
            displayName: option.displayName ?? option.id,
          })),
    [hostClaudeModelOptions, sandboxSelected],
  );
  const codexModelOptions = useMemo(
    () => (sandboxSelected ? [] : (hostCodexModelOptions ?? [])),
    [hostCodexModelOptions, sandboxSelected],
  );
  const [workspace, setWorkspace] = useState<string>(() =>
    projectParam === "" ? (landingDraft?.workspace ?? "") : "",
  );
  const [branchName, setBranchName] = useState<string>(() =>
    projectParam === "" ? (landingDraft?.branchName ?? "") : "",
  );
  // A Project may opt into an isolated worktree. The branch is generated from
  // that project policy; it is not a Session-level location control.
  const [baseBranch, _setBaseBranch] = useState<string>("");
  // Branch prefilled from the existing worktree the current workspace points
  // at. When `branchName` still equals this, the session starts directly in
  // that worktree (no git opts). Editing the field away from it means the user
  // wants a *new* worktree off that name.
  const [prefilledBranch, setPrefilledBranch] = useState<string>(() =>
    projectParam === "" ? (landingDraft?.prefilledBranch ?? "") : "",
  );
  // Project to file the new session under. Empty = unfiled. Stamped as the
  // `omni_project` label at create (so the row is filed from its first sidebar
  // appearance), then promoted to first-class `project_id` right after.
  // Pre-filled from the `?project=` param so the sidebar's per-project
  // "new session" pencil lands here with the project already selected.
  const [selectedProject, setSelectedProject] = useState<string>(() => projectParam);
  // The landing screen stays mounted while the `?project=` param changes (e.g.
  // clicking a different project's pencil), so the lazy initializer above won't
  // re-run — sync the selection to the param whenever it changes.
  useEffect(() => {
    setSelectedProject(projectParam);
  }, [projectParam]);
  // Permission mode for Claude Code (claude --permission-mode). Only
  // meaningful for the claude-native wrapper; ignored otherwise. Lives in
  // the footer tray's Advanced settings menu.
  const [permissionMode, setPermissionMode] = useState<string>(
    () => landingDraft?.permissionMode ?? CLAUDE_NATIVE_DEFAULT_PERMISSION_MODE,
  );
  // Approval mode for Codex (codex --approval-mode). Only meaningful for
  // the codex-native wrapper; ignored otherwise. Lives in the footer
  // tray's Advanced settings menu.
  const [approvalMode, setApprovalMode] = useState<string>(
    () => landingDraft?.approvalMode ?? CODEX_NATIVE_DEFAULT_APPROVAL_MODE,
  );
  // DANGEROUS codex full-bypass opt-in (Codex only). OFF by default and only
  // flippable on after the user types the confirmation phrase, so it can
  // never be enabled by an accidental click. Persisted as a conversation
  // label so it survives reload. When on, a persistent red banner warns and
  // the runner ignores the approval-mode preset's flags.
  const [bypassSandbox, setBypassSandbox] = useState<boolean>(
    () => landingDraft?.bypassSandbox ?? false,
  );
  // Execution mode for Cursor (cursor-agent --mode / --yolo). Only meaningful
  // for the cursor-native wrapper; ignored otherwise.
  const [cursorExecMode, setCursorExecMode] = useState<string>(
    () => landingDraft?.cursorExecMode ?? CURSOR_NATIVE_DEFAULT_EXEC_MODE,
  );
  // Per-session brain-harness override for bundle agents (polly / debby).
  // null = the agent spec's declared harness (no override sent). On agent
  // switch, seeded from the user's last stored pick for that agent.
  const [pickedHarness, setPickedHarness] = useState<string | null>(
    () =>
      landingDraft?.pickedHarness ??
      readLastHarness(landingDraft?.pickedAgentId ?? readLastAgentId()),
  );
  // Per-session model + reasoning effort for the claude-native model picker.
  // "" = unselected: nothing is checked and `model_override` / `reasoning_effort`
  // are omitted from the create, so Claude Code uses its own configured model.
  // An explicit pick rides along and is remembered (seeded back on a later visit
  // via the harness-seed effect below).
  const [pickedModel, _setPickedModel] = useState<string>(() => landingDraft?.pickedModel ?? "");
  const [pickedEffort, setPickedEffort] = useState<string>(() => landingDraft?.pickedEffort ?? "");
  // Per-session cost-control switch ("Cost Optimized" pill). Unset
  // (null) defers to the agent spec's default and is omitted from
  // the create body.
  const [costControlMode, _setCostControlMode] = useState<CostControlMode>(
    () => landingDraft?.costControlMode ?? null,
  );
  // Model selection and smart routing are mutually exclusive: enabling
  // routing clears the explicit model pick, and picking a model turns
  // routing off.
  const setPickedModel = useCallback((model: string) => {
    _setPickedModel(model);
    if (model) _setCostControlMode(null);
  }, []);
  const setCostControlMode = useCallback((mode: CostControlMode) => {
    _setCostControlMode(mode);
    if (mode === "on") _setPickedModel("");
  }, []);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  // Harness "Set up" dialog target, opened from the composer notice or a picker
  // row; null when closed. One dialog serves every entry point.
  const [setupTarget, setSetupTarget] = useState<{
    agentName: string | undefined;
    harness: string | null;
    host: Host | undefined | null;
  } | null>(null);
  // Harness-config modal, opened from the composer's gear icon.
  const [configOpen, setConfigOpen] = useState(false);

  // Mirror the current draft fields into a ref every render so the unmount
  // cleanup below can snapshot the latest values without re-subscribing.
  // `submittedRef` is flipped just before we navigate to a freshly-created
  // session so the snapshot is dropped instead of resurrected.
  const submittedRef = useRef(false);
  const draftRef = useRef<LandingDraft>(null as unknown as LandingDraft);
  draftRef.current = {
    message,
    files,
    pickedAgentId,
    selectedHostId,
    sandboxSelected,
    workspace,
    branchName,
    prefilledBranch,
    permissionMode,
    approvalMode,
    bypassSandbox,
    cursorExecMode,
    pickedHarness,
    pickedModel,
    pickedEffort,
    costControlMode,
  };
  useEffect(() => {
    return () => {
      landingDraft = submittedRef.current ? null : draftRef.current;
    };
  }, []);

  const allHosts = hosts ?? [];
  const onlineHosts = allHosts.filter((h) => h.status === "online");

  // Project prefill: a project-driven visit seeds the composer from the
  // project's stored defaults (host / working directory / agent / worktree).
  // `?project=` carries the project NAME, so resolve it to the first-class id
  // the config endpoint needs; a label-only folder (id null) or plain visit
  // has no config to read.
  const {
    data: projectList,
    isLoading: projectListLoading,
    isSuccess: projectListLoaded,
  } = useProjects();
  const projectExists = useMemo(
    () =>
      projectParam === "" || (projectList ?? []).some((project) => project.name === projectParam),
    [projectList, projectParam],
  );
  // A project deep link can outlive its project (for example, the user opens
  // "New session" and then deletes the empty project from another surface).
  // Once the authoritative project list has loaded, remove that stale scope
  // from both the URL and the submit state. Leaving selectedProject populated
  // would let handleCreate recreate the deleted project by name.
  useEffect(() => {
    if (!projectListLoaded || projectExists) return;
    const next = new URLSearchParams(searchParams);
    next.delete("project");
    setSelectedProject("");
    setSearchParams(next, { replace: true });
  }, [projectExists, projectListLoaded, searchParams, setSearchParams]);
  const configProjectId = useMemo(
    () =>
      projectParam !== ""
        ? ((projectList ?? []).find((p) => p.name === projectParam)?.id ?? null)
        : null,
    [projectList, projectParam],
  );
  const { data: storedProjectConfig, isLoading: projectConfigLoading } =
    useProjectConfig(configProjectId);
  // Normalize into the machine's shape. `undefined` = still loading (the machine
  // waits so a generic default can't win the race); `{}` = nothing to wait for
  // (plain visit / label-only folder / genuinely empty config), so it settles
  // immediately and the generic defaults take over.
  const prefillConfig = useMemo<ProjectPrefillConfig | undefined>(() => {
    // A project-scoped visit must resolve name → id via the projects list
    // before we know whether there's a config to read — until it loads, the id
    // is falsely null, so wait rather than settle prematurely.
    if (projectParam !== "" && projectListLoading) return undefined;
    if (configProjectId !== null && projectConfigLoading) return undefined;
    const c = storedProjectConfig;
    if (!c) return {};
    return {
      hostId: c.host_id,
      workspace: c.workspace,
      agentId: c.agent_id,
      useWorktree: c.use_worktree,
    };
  }, [
    projectParam,
    projectListLoading,
    configProjectId,
    projectConfigLoading,
    storedProjectConfig,
  ]);
  const selectedProjectRecord = useMemo(
    () => (projectList ?? []).find((project) => project.name === selectedProject) ?? null,
    [projectList, selectedProject],
  );
  const selectedProjectId = selectedProjectRecord?.id ?? null;
  // A first-class Project with a persisted execution target is a binding, not
  // merely a set of composer defaults. External hosts require a source folder;
  // a managed sandbox can intentionally have none (the server creates an empty
  // workspace). Keep execution chips out of this path: the Project chip is the
  // single place to change the session's location.
  const projectBoundHostId = selectedProject ? storedProjectConfig?.host_id : undefined;
  const projectBoundWorkspace = selectedProject ? storedProjectConfig?.workspace : undefined;
  const projectUsesManagedWorkspace = projectBoundHostId === SANDBOX_HOST_CHOICE;
  const projectWorkspaceBound = Boolean(
    selectedProject && projectBoundHostId && (projectUsesManagedWorkspace || projectBoundWorkspace),
  );
  const projectWorkspaceMalformed = Boolean(
    selectedProject &&
    !projectListLoading &&
    !projectConfigLoading &&
    (!projectWorkspaceBound ||
      (projectBoundHostId && !projectUsesManagedWorkspace && !projectBoundWorkspace) ||
      (!projectBoundHostId && projectBoundWorkspace)),
  );
  const projectBoundHostAvailable = projectUsesManagedWorkspace
    ? managedSandboxesEnabled
    : Boolean(
        projectBoundHostId && onlineHosts.some((host) => host.host_id === projectBoundHostId),
      );
  const projectHostAvailabilityKnown = projectUsesManagedWorkspace
    ? info !== "loading"
    : !hostsLoading;
  const projectWorkspaceLoading = projectWorkspaceBound && !projectHostAvailabilityKnown;
  const projectWorkspaceUnavailable =
    projectWorkspaceBound && projectHostAvailabilityKnown && !projectBoundHostAvailable;
  // State machine driving the project prefill: a location seed (host +
  // workspace from config) plus an independent agent seed. The generic
  // host/workspace defaults below hold off until it settles so they can't win
  // the race against the project's stored values.
  const [prefill, setPrefill] = useState<ProjectPrefillState>(() =>
    initialPrefillState(projectParam),
  );
  // The generic defaults gate on the location track only — the agent seed
  // waits on its own fetch and must not hold up the host/workspace fill.
  const prefillSettled = prefill.phase === "settled";
  // Workspace the opt-in worktree effect already acted on, so it fires at most
  // once per settled workspace (and can't loop once it sets a branch name).
  const worktreeSeededForRef = useRef<string | null>(null);

  // The landing screen stays mounted while `?project=` changes (clicking
  // another project's pencil), so re-create a fresh visit by hand: clear
  // every seedable slot and restart the machine. Values the user set are
  // reset too — a pencil click means "set me up for this project".
  useEffect(() => {
    if (prefill.project === projectParam) return;
    setSandboxSelected(false);
    setSelectedHostId(null);
    setPickedAgentId(projectParam !== "" ? null : readLastAgentId());
    setWorkspace("");
    setBranchName("");
    worktreeSeededForRef.current = null;
    setPrefill(initialPrefillState(projectParam));
  }, [projectParam, prefill.project]);

  // An unfiled session is always a managed sandbox. A Project session gets its
  // execution target from the Project config and never falls back to another
  // host or a recent directory.
  useEffect(() => {
    if (!prefillSettled) return;
    // An unfiled session has no user-selected execution location. It is an
    // intentionally empty managed sandbox; external hosts require a Project
    // because their runner needs a Project-owned absolute workspace.
    if (!selectedProject) {
      if (info === "loading") return;
      setSandboxSelected(managedSandboxesEnabled);
      setSelectedHostId(null);
      setWorkspace("");
      return;
    }
    // A bound Project is authoritative even when its host is offline. Never
    // fall back to another host: that would display one location while the
    // server correctly rejects the override against the Project binding.
    if (projectWorkspaceBound || projectWorkspaceMalformed) return;
  }, [
    managedSandboxesEnabled,
    info,
    prefillSettled,
    selectedProject,
    projectWorkspaceBound,
    projectWorkspaceMalformed,
  ]);

  // A pick only wins while it exists in the list — a persisted id whose
  // agent has since been unregistered (or hidden) falls back to the default.
  // The pending custom agent sentinel also wins when set.
  // A pending (just-created, not-yet-submitted) custom agent can't run on a
  // managed sandbox — the sandbox create path doesn't provision a runner for a
  // bundled agent. So a pending pick made before switching to a sandbox is
  // dropped there, falling back to a real agent; off the sandbox it's kept.
  const pendingAgentAllowedOnTarget = !sandboxSelected;
  const effectiveAgentId =
    pickedAgentId === PENDING_AGENT_ID && pendingAgentAllowedOnTarget
      ? PENDING_AGENT_ID
      : ((agentList.some((a) => a.id === pickedAgentId) ? pickedAgentId : agentList[0]?.id) ??
        null);
  const selectedAgent = useMemo(
    () =>
      effectiveAgentId === PENDING_AGENT_ID && pendingAgent
        ? ({
            id: PENDING_AGENT_ID,
            name: pendingAgent.name,
            display_name: pendingAgent.name,
            description: pendingAgent.description ?? null,
            harness: pendingAgent.harness ?? null,
            skills: [],
          } satisfies AvailableAgent)
        : agentList.find((a) => a.id === effectiveAgentId),
    [agentList, effectiveAgentId, pendingAgent],
  );
  const supportsPermissionMode = nativeAgentHasCapability(selectedAgent, "permissionMode");
  const supportsApprovalMode = nativeAgentHasCapability(selectedAgent, "approvalMode");
  const supportsCursorMode = nativeAgentHasCapability(selectedAgent, "cursorMode");
  const hideUnconfiguredHarnesses = useMemo(() => readHideUnconfiguredHarnesses(), []);
  // Smart Routing (per-session model selection) is superseded by the Auto
  // harness which handles both harness + model. Hide it entirely for now.
  const smartRoutingEligible = false;
  // Whether the gear config modal has anything to show for the selected agent
  // (drives the gear icon's visibility). Bundle agents with an overridable
  // brain harness qualify, as does any routing-eligible agent — Smart Routing
  // lives only in the modal now, so an agent with just that (e.g. Pi) still
  // needs the gear.
  const selectedAgentHasKnobs =
    supportsPermissionMode ||
    supportsApprovalMode ||
    supportsCursorMode ||
    smartRoutingEligible ||
    (selectedAgent?.harness != null && selectedAgent.harness in brainHarnessLabels);
  // Label/value pairs summarizing the selected agent's current run-config, for
  // the gear icon's hover tooltip. Mirrors the modal's per-capability rows so a
  // user can read the active settings without opening it. "Default" = an unset
  // model/effort (Claude Code uses its own configured default).
  // Gate on eligibility so a stale "on" (server flag off, or a non-routable
  // agent) never shows misleading Smart Routing rows in the tooltip.
  const routingOn = smartRoutingEligible && costControlMode === "on";
  const configSummary = useMemo((): { label: string; value: string }[] => {
    if (supportsPermissionMode) {
      const modelValue = routingOn
        ? t("smartRouting")
        : (claudeModelOptions.find((m) => m.id === pickedModel)?.displayName ??
          t("reasoning.default"));
      // Smart Routing freezes effort to the default (the router picks per turn),
      // so mirror the modal: show "Default" whenever routing is on or effort is
      // unset, else the picked level.
      const effortValue =
        routingOn || !pickedEffort
          ? t("reasoning.default")
          : translateConfigOptionLabel(
              t,
              pickedEffort,
              CLAUDE_NATIVE_EFFORTS.find((e) => e.value === pickedEffort)?.label ?? pickedEffort,
            );
      const permissionValue = translateConfigOptionLabel(
        t,
        permissionMode,
        CLAUDE_NATIVE_PERMISSION_MODES.find((m) => m.value === permissionMode)?.label ??
          permissionMode,
      );
      return [
        { label: t("model"), value: modelValue },
        { label: t("summaryEffort"), value: effortValue },
        { label: t("permissions"), value: permissionValue },
      ];
    }
    // Non-Claude routable agents surface Smart Routing as a standalone toggle,
    // so reflect it here when on (Claude folds it into Model above).
    const routingRow: { label: string; value: string }[] =
      smartRoutingEligible && routingOn
        ? [{ label: t("smartRouting"), value: t("configOptions.labels.auto") }]
        : [];
    if (supportsApprovalMode) {
      const isCodex = nativeCodingAgentForAvailableAgent(selectedAgent)?.harness === "codex-native";
      // Bypass is the most-permissive Approval choice, not a separate knob — so
      // mirror the modal's single Approval control: when armed, the Approval row
      // reads "Bypass approvals & sandbox" rather than the underlying preset
      // (which would misleadingly imply approvals are still at e.g. "Default").
      const approvalValue =
        isCodex && bypassSandbox
          ? translateConfigOptionLabel(
              t,
              CODEX_NATIVE_BYPASS_APPROVAL_OPTION.value,
              CODEX_NATIVE_BYPASS_APPROVAL_OPTION.label,
            )
          : translateConfigOptionLabel(
              t,
              approvalMode,
              CODEX_NATIVE_APPROVAL_MODES.find((m) => m.value === approvalMode)?.label ??
                approvalMode,
            );
      const modelRows = isCodex
        ? [
            {
              label: t("model"),
              value:
                codexModelOptions.find((m) => m.id === pickedModel)?.id ??
                defaultModelLabel(codexModelOptions, displayModelId).replace(
                  /^Default/,
                  t("reasoning.default"),
                ),
            },
          ]
        : [];
      return [...modelRows, { label: t("approval"), value: approvalValue }, ...routingRow];
    }
    if (supportsCursorMode) {
      const modeValue = translateConfigOptionLabel(
        t,
        cursorExecMode,
        CURSOR_NATIVE_EXEC_MODES.find((m) => m.value === cursorExecMode)?.label ?? cursorExecMode,
      );
      return [{ label: t("mode"), value: modeValue }, ...routingRow];
    }
    if (selectedAgent?.harness != null && selectedAgent.harness in brainHarnessLabels) {
      const active = pickedHarness ?? selectedAgent.harness;
      return [
        { label: t("summaryHarness"), value: brainHarnessLabels[active] ?? active },
        ...routingRow,
      ];
    }
    return routingRow;
  }, [
    supportsPermissionMode,
    supportsApprovalMode,
    supportsCursorMode,
    smartRoutingEligible,
    selectedAgent,
    brainHarnessLabels,
    routingOn,
    pickedModel,
    claudeModelOptions,
    codexModelOptions,
    pickedEffort,
    permissionMode,
    approvalMode,
    bypassSandbox,
    cursorExecMode,
    pickedHarness,
    t,
  ]);
  // Reset per-agent-instance run-config that must not carry across an agent
  // change. The DANGEROUS Codex bypass re-opts-in per context (matching the
  // store's fork / agent-switch behavior; CODEX_NATIVE_BYPASS_SANDBOX_LABEL_KEY
  // is instance-scoped). Smart routing likewise clears: switching to an agent
  // whose modal has no routing control (or isn't routable) would otherwise
  // leave it stuck "on" with no UI to turn it off.
  //
  // Only reset on an ACTUAL agent change — not the initial resolution (null →
  // first id, or a persisted/draft pick resolving on mount), which would wipe a
  // costControlMode/bypass restored from the landing draft.
  const prevAgentIdRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const prev = prevAgentIdRef.current;
    prevAgentIdRef.current = effectiveAgentId;
    if (prev === undefined || prev === effectiveAgentId) return;
    setBypassSandbox(false);
    setCostControlMode(null);
  }, [effectiveAgentId, setCostControlMode]);
  // The selected native harness, used to persist/seed its option knobs (mode /
  // model / effort), which are harness-specific. null for non-native agents,
  // which have no knobs to remember.
  const selectedNativeHarness = nativeCodingAgentForAvailableAgent(selectedAgent)?.harness ?? null;
  // Seed the harness's knobs from the user's last picks when the selected
  // harness changes (including the first mount), so a returning user starts a
  // new session on the options they used last for that harness instead of the
  // default. Keyed on the harness so an in-session edit isn't clobbered on
  // re-render — only a harness switch reseeds.
  useEffect(() => {
    if (!selectedNativeHarness) return;
    const stored = readHarnessOptions(selectedNativeHarness);
    // Resolve the mode to the stored value when it's still valid for this
    // harness, else the harness default. The else branch must RESET (not
    // early-return) because codex-native and opencode-native share the single
    // approvalMode state: returning early would leave the previously-selected
    // harness's mode in place — e.g. codex's "full-access" carried onto
    // OpenCode — and flow into the launch args unchanged. A stale value not in
    // the current list resolves to the default for the same reason.
    const resolve = (modes: readonly { value: string }[], dflt: string) =>
      stored.mode != null && modes.some((m) => m.value === stored.mode) ? stored.mode : dflt;
    if (supportsPermissionMode) {
      setPermissionMode(
        resolve(CLAUDE_NATIVE_PERMISSION_MODES, CLAUDE_NATIVE_DEFAULT_PERMISSION_MODE),
      );
      // The model + effort picker remembers its own last pick (same per-harness
      // snapshot the mode knob uses), validated against the current vocab. With
      // nothing stored (or a retired id) it resolves to "" — unselected, so the
      // create omits the override and Claude Code uses its own configured model.
      setPickedModel(
        stored.model != null && claudeModelOptions.some((m) => m.id === stored.model)
          ? stored.model
          : "",
      );
      setPickedEffort(
        stored.effort != null && CLAUDE_NATIVE_EFFORTS.some((e) => e.value === stored.effort)
          ? stored.effort
          : "",
      );
    } else if (supportsApprovalMode) {
      setApprovalMode(resolve(CODEX_NATIVE_APPROVAL_MODES, CODEX_NATIVE_DEFAULT_APPROVAL_MODE));
      setPickedModel(
        selectedNativeHarness === "codex-native" &&
          stored.model != null &&
          codexModelOptions.some((m) => m.id === stored.model)
          ? stored.model
          : "",
      );
    } else if (supportsCursorMode) {
      setCursorExecMode(resolve(CURSOR_NATIVE_EXEC_MODES, CURSOR_NATIVE_DEFAULT_EXEC_MODE));
    }
    // Reseed on harness changes and when the selected host's catalog resolves;
    // capability flags are derived from the same harness and stay omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNativeHarness, claudeModelOptions, codexModelOptions]);
  // Native-terminal agents interpret slash commands inside their own CLI
  // (the runner injects the text verbatim), so the landing composer must
  // not intercept them — no skills menu, no slash_command routing.
  const isNativeTerminalAgent = isNativeCodingAgent(selectedAgent);
  const selectedHost = allHosts.find((h) => h.host_id === selectedHostId);
  // Readiness for the actual execution target. A managed sandbox provisions
  // its own tooling, so connected-Host readiness is irrelevant there.
  const harnessWarningHost = !sandboxSelected ? selectedHost : undefined;
  // When managed sandboxes are unavailable, the unfiled landing page still
  // displays "New Sandbox" with no selectedHostId. Use the first online local
  // Host only for picker grouping/badges so installed CLIs stay inline and
  // missing ones remain labeled under More. Do not feed this fallback into
  // launch warnings/config: it is not the session target.
  const localReadinessFallback =
    !selectedProject && !managedSandboxesEnabled ? onlineHosts[0] : undefined;
  const pickerReadinessHost = harnessWarningHost ?? localReadinessFallback;
  const selectedAgentUnconfigured = harnessUnconfiguredOnHost(
    selectedAgent?.harness,
    harnessWarningHost,
  );
  const workspaceTrimmed = workspace.trim();

  // Project worktree policy is resolved automatically. The Session composer
  // never exposes a directory or branch picker; this probe is only used to
  // avoid asking the runner for a worktree when the Project workspace is not a
  // git repository, or to preserve an existing worktree binding.
  const worktreesEnabled =
    Boolean(selectedProject) &&
    !sandboxSelected &&
    selectedHostId !== null &&
    workspaceTrimmed !== "";
  const { data: hostWorktrees, isPlaceholderData: hostWorktreesArePlaceholder } = useHostWorktrees(
    worktreesEnabled ? selectedHostId : null,
    worktreesEnabled ? workspaceTrimmed : null,
  );
  // The Project workspace may already be an existing worktree. Detect that
  // state without exposing a Session-level worktree control.
  const activeWorktree = useMemo(() => {
    const target = workspaceTrimmed.replace(/\/+$/, "") || null;
    if (target === null) return null;
    return (
      (hostWorktrees ?? []).find(
        (w) => !w.is_main && (w.path.replace(/\/+$/, "") || "/") === target,
      ) ?? null
    );
  }, [hostWorktrees, workspaceTrimmed]);
  // Preserve an existing Project worktree's branch for the server-side launch
  // contract. This is derived data, not user-editable Session state.
  useEffect(() => {
    const branch = activeWorktree?.branch ?? "";
    if (branch !== "") {
      setPrefilledBranch(branch);
      setBranchName(branch);
    } else {
      setPrefilledBranch((prev) => {
        // Only clear the field if it still holds the previous Project-derived
        // value; there is no Session input that could need preserving here.
        setBranchName((cur) => (cur === prev ? "" : cur));
        return "";
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorktree?.path]);
  // True when the session should start directly in the existing worktree:
  // the workspace is a worktree and the branch field still holds its
  // prefilled branch (the user hasn't edited it to request a new worktree).
  const startInExistingWorktree =
    activeWorktree !== null && prefilledBranch !== "" && branchName.trim() === prefilledBranch;
  // A new isolated worktree is created only when the Project policy generated
  // a branch and the configured workspace is not already that worktree.
  const shouldCreateWorktree = branchName.trim() !== "" && !startInExistingWorktree;
  // Base branch is also a Project policy/default, never a Session input.
  useEffect(() => {
    if (!shouldCreateWorktree) {
      _setBaseBranch("");
      return;
    }
    _setBaseBranch(readDefaultBaseBranch() ?? "");
  }, [shouldCreateWorktree]);
  // Generate the branch required by a Project's use_worktree policy.
  const generateBranchName = useCallback(() => {
    const suffix = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
    setBranchName(`worktree-${suffix}`);
  }, []);
  // Project prefill: seed host / workspace / agent from the project's stored
  // config, then settle so the generic defaults fill any slot the config left
  // unset. An opt-in worktree is generated by the dedicated effect below once
  // the workspace is in place.
  useEffect(() => {
    if (prefill.project !== projectParam || prefillDone(prefill)) return;
    const step = projectPrefillStep(prefill, {
      hosts,
      // The pickable list, not the raw one — a hidden agent's id would seed
      // a pick that effectiveAgentId rejects. Raw undefined = still loading.
      agents: agents === undefined ? undefined : agentList,
      sandboxSelected,
      managedSandboxesEnabled,
      selectedHostId,
      lastAgentId: readLastAgentId(),
      config: prefillConfig,
    });
    if (step === null) return;
    const { writes } = step;
    if (writes.selectSandbox) setSandboxSelected(true);
    if (writes.hostId !== undefined) setSelectedHostId((cur) => cur ?? writes.hostId!);
    if (writes.agentId !== undefined) {
      setPickedAgentId((cur) => cur ?? writes.agentId!);
      if (pickedAgentId === null) setPickedHarness(readLastHarness(writes.agentId));
    }
    if (writes.workspace !== undefined) {
      setWorkspace((cur) => (cur === "" ? writes.workspace! : cur));
    }
    setPrefill(step.state);
  }, [
    prefill,
    projectParam,
    hosts,
    agents,
    agentList,
    sandboxSelected,
    managedSandboxesEnabled,
    selectedHostId,
    pickedAgentId,
    prefillConfig,
  ]);

  // Opt-in worktree from the project's stored config. The inference machine
  // settles a config-driven location without touching the branch, so this
  // effect creates the fresh worktree once the workspace is fully in place —
  // whether it came from the config's own workspace or the composer's
  // home-fallback (which runs after the machine settles). Fires at most once
  // per settled workspace (ref-guarded) and only into an empty branch, so a
  // typed branch / existing-worktree prefill is never clobbered.
  useEffect(() => {
    if (prefillConfig?.useWorktree !== true) return;
    if (prefill.project !== projectParam || !prefillDone(prefill)) return;
    if (sandboxSelected || selectedHostId === null || workspaceTrimmed === "") return;
    if (branchName !== "" || prefilledBranch !== "") return;
    if (worktreeSeededForRef.current === workspaceTrimmed) return;
    // Need the git-ness probe for the CURRENT workspace resolved (not the
    // anti-flicker placeholder from a previous path).
    if (hostWorktreesArePlaceholder || hostWorktrees === undefined) return;
    worktreeSeededForRef.current = workspaceTrimmed;
    if (hostWorktrees.some((w) => w.is_main)) generateBranchName();
  }, [
    prefillConfig,
    prefill,
    projectParam,
    sandboxSelected,
    selectedHostId,
    workspaceTrimmed,
    branchName,
    prefilledBranch,
    hostWorktrees,
    hostWorktreesArePlaceholder,
    generateBranchName,
  ]);

  // Slash-command suggestions for the chosen agent's bundled skills.
  // Mirrors the in-session composer's menu mechanics (open while the
  // command name is still being typed: leading "/", no second "/", no
  // space yet), but lists skills only — built-ins like /model need a
  // live session. Hidden for native-terminal agents (their CLI owns
  // slash commands) and for agents without bundled skills.
  const [slashMenuIndex, setSlashMenuIndex] = useState(-1);
  const skillCommands = useMemo(() => {
    if (isNativeTerminalAgent) return {};
    const m: Record<string, string> = {};
    for (const s of selectedAgent?.skills ?? []) m[`/${s.name}`] = s.description;
    return m;
  }, [selectedAgent, isNativeTerminalAgent]);
  const trimmedMessage = message.trimStart();
  const slashMenuOpen =
    trimmedMessage.startsWith("/") &&
    !trimmedMessage.slice(1).includes("/") &&
    !trimmedMessage.includes(" ");
  const slashMenuQuery = slashMenuOpen ? trimmedMessage.slice(1) : "";
  // Kept in sync with what SlashCommandMenu renders so keyboard nav
  // indexes into the same list.
  const slashMenuMatches = slashMenuOpen
    ? rankedSlashCommandNames(skillCommands, slashMenuQuery)
    : [];
  // Pre-select the first match whenever the filtered list changes, so
  // Tab/Enter complete the top item without arrowing down first (same
  // reset pattern as the in-session composer).
  const prevSlashMatchesRef = useRef<string[]>([]);
  if (
    slashMenuMatches.length !== prevSlashMatchesRef.current.length ||
    slashMenuMatches.some((m, i) => m !== prevSlashMatchesRef.current[i])
  ) {
    prevSlashMatchesRef.current = slashMenuMatches;
    setSlashMenuIndex(slashMenuMatches.length > 0 ? 0 : -1);
  }

  // Selecting a skill fills "/name " and leaves the caret ready for the
  // argument — skills never auto-execute from the menu.
  function applySlashSelection(cmd: string) {
    setSlashMenuIndex(-1);
    setMessage(cmd + " ");
    textareaRef.current?.focus();
  }

  // Always-visible skill pills for the allowlisted orchestrators, fed by
  // the same bundled-skills list as the "/" menu.
  const pillSkills =
    selectedAgent && SKILL_PILL_AGENTS.has(selectedAgent.name) ? selectedAgent.skills : [];

  // Pills only render over an empty draft, so there's never args to preserve.
  function applySkillPill(name: string) {
    setMessage(`/${name} `);
    textareaRef.current?.focus();
  }

  // ── "@"-file-mention browser (parity with the in-session composer) ────────
  // Only for native terminal agents on a real local host with an absolute
  // workspace. No session/runner exists yet, so the listing comes from the
  // host filesystem endpoint (absolute paths) rather than the session-scoped
  // workspace API; each tagged path is delivered as an "[Attached: …]" marker
  // prepended to the first message, which the runner reads from that workspace.
  const [mention, setMention] = useState<MentionState | null>(null);
  const mentionEnabled =
    isNativeTerminalAgent &&
    !!selectedProject &&
    !sandboxSelected &&
    !!selectedHostId &&
    projectWorkspaceBound &&
    workspaceTrimmed !== "";
  const { dir: mentionDir, filter: mentionFilter } = parseMentionToken(mention?.query ?? "");
  const workspaceRoot = workspaceTrimmed.replace(/\/+$/, "");
  // Absolute dir to list = workspace root + the drilled sub-path.
  const mentionAbsDir =
    mentionEnabled && mention
      ? mentionDir
        ? `${workspaceRoot}/${mentionDir}`
        : workspaceRoot
      : null;
  const mentionFsQuery = useHostFilesystem(
    mentionEnabled && mention ? selectedHostId : null,
    mentionAbsDir,
  );
  // Map host entries (absolute paths) to workspace-relative WorkspaceFile rows,
  // then rank (folders-first, filtered, capped) via the shared helper.
  const mentionEntries: WorkspaceFile[] = useMemo(() => {
    if (!mentionEnabled || !mention) return [];
    // ``useHostFilesystem`` keeps the previous directory's rows as placeholder
    // data (no flicker on navigate). When the user drills into a folder a new
    // fetch starts but ``data`` still holds the *parent's* entries — ``isLoading``
    // is false, only ``isPlaceholderData`` is true. Returning those stale rows
    // here would show the parent's files while purporting to be inside the
    // child, so a click/Enter could attach the wrong entry. Suppress them until
    // the current directory's own listing arrives.
    if (mentionFsQuery.isPlaceholderData) return [];
    const rows = (mentionFsQuery.data?.entries ?? [])
      .filter((e) => e.type === "directory" || e.type === "file")
      .map((e): WorkspaceFile => ({
        path: e.path.startsWith(workspaceRoot)
          ? e.path.slice(workspaceRoot.length).replace(/^\/+/, "")
          : e.name,
        name: e.name,
        type: e.type === "directory" ? "directory" : "file",
        bytes: e.bytes,
        modified_at: e.modified_at,
      }));
    return rankMentionEntries(rows, mentionFilter);
  }, [
    mentionEnabled,
    mention,
    mentionFsQuery.data,
    mentionFsQuery.isPlaceholderData,
    mentionFilter,
    workspaceRoot,
  ]);
  const mentionOpen = mentionEntries.length > 0;
  // Closed-but-loading window: don't let Enter send the half-typed "@dir/".
  // ``isPlaceholderData`` covers the drill-down window where react-query is
  // still serving the previous directory's rows (``isLoading`` stays false).
  const mentionListingPending =
    mentionEnabled &&
    mention != null &&
    (mentionFsQuery.isLoading || mentionFsQuery.isPlaceholderData);

  // Shared selection/chip/keyboard glue — see useMentionBrowser. Only the
  // host-filesystem source + token state above are launcher-specific.
  const {
    mentionIndex,
    mentionedItems,
    attachMention,
    openMentionDir,
    removeMentionedItem,
    handleKeyDown: handleMentionKeyDown,
    dismiss: dismissMention,
  } = useMentionBrowser({
    mention,
    setMention,
    mentionEntries,
    text: message,
    setText: setMessage,
    textareaRef,
  });

  const projectLocationReady = selectedProject
    ? prefillDone(prefill) &&
      projectWorkspaceBound &&
      !projectWorkspaceLoading &&
      !projectWorkspaceMalformed &&
      !projectWorkspaceUnavailable
    : managedSandboxesEnabled && sandboxSelected && selectedHostId === null;
  const canSubmit =
    message.trim().length > 0 && selectedAgent != null && projectLocationReady && !creating;

  // Why submit is disabled, surfaced as the button's tooltip. Checked in the
  // order a user fills the form — location first, then message — so the
  // tooltip always names the next missing input. Null when nothing is
  // actionable (submitting, or mid-create).
  const submitDisabledReason = canSubmit
    ? null
    : !selectedProject && !managedSandboxesEnabled
      ? commonT("shell.noProjectSandboxUnavailable")
      : selectedProject && (!prefillDone(prefill) || projectWorkspaceLoading)
        ? commonT("shell.projectLoading")
        : projectWorkspaceMalformed
          ? commonT("shell.projectWorkspaceInvalid")
          : projectWorkspaceUnavailable
            ? commonT("shell.projectHostUnavailable")
            : message.trim().length === 0
              ? "Enter a message to get started"
              : null;

  // The trigger label is just the agent name; the run-config knobs live in
  // the picker's per-entry submenu, so duplicating their values here would be
  // redundant.
  const agentLabel = selectedAgent
    ? selectedAgent.display_name
    : t("picker.selectAgent", { ns: "agents" });
  const boundHost = projectBoundHostId
    ? (allHosts.find((host) => host.host_id === projectBoundHostId) ?? selectedHost)
    : selectedHost;
  const inheritedHostLabel = !selectedProject
    ? sandboxLabel
    : projectUsesManagedWorkspace
      ? sandboxLabel
      : (boundHost?.name ?? projectBoundHostId ?? commonT("shell.projectLoading"));
  const inheritedHostHealthy = !selectedProject
    ? managedSandboxesEnabled
    : projectUsesManagedWorkspace
      ? managedSandboxesEnabled
      : boundHost?.status === "online";
  const inheritedHostStatus =
    info === "loading" || (selectedProject && projectHostAvailabilityKnown === false)
      ? "loading"
      : inheritedHostHealthy
        ? "online"
        : "offline";
  const inheritedWorkspaceLabel = selectedProject
    ? projectWorkspaceBound
      ? projectUsesManagedWorkspace
        ? commonT("shell.managedWorkspace")
        : (projectBoundWorkspace ?? commonT("shell.projectLoading"))
      : projectWorkspaceMalformed
        ? commonT("shell.projectWorkspaceInvalid")
        : commonT("shell.projectLoading")
    : null;

  // Wrap the harness setter so every explicit pick is persisted to
  // localStorage. The caller can pass an explicit `agentId` for the
  // switch-via-submenu path where `effectiveAgentId` still reflects the
  // previously selected agent (the state update from `onSelectAgent` hasn't
  // applied yet).
  const handleSetPickedHarness = useCallback(
    (harness: string | null, agentId?: string) => {
      setPickedHarness(harness);
      writeLastHarness(agentId ?? effectiveAgentId, harness);
      // Light up the routing icon when "Auto" is picked; turn it off otherwise.
      _setCostControlMode(harness === AUTO_HARNESS_ID ? "on" : null);
    },
    [effectiveAgentId],
  );

  // Select an agent/harness from the picker. Switching agents seeds the
  // harness override from the user's last pick for that agent (so a
  // returning user lands on the harness they used last); explicit picks
  // persist via localStorage.
  const handleSelectAgent = (agent: AvailableAgent) => {
    if (agent.id !== effectiveAgentId) setPickedHarness(readLastHarness(agent.id));
    setPickedAgentId(agent.id);
    writeLastAgentId(agent.id);
  };
  const handleSelectPending = () => {
    setPickedAgentId(PENDING_AGENT_ID);
    setPickedHarness(null);
  };

  function selectProject(projectName: string) {
    const next = new URLSearchParams(searchParams);
    if (projectName === "") next.delete("project");
    else next.set("project", projectName);
    setSelectedProject(projectName);
    setSearchParams(next, { replace: true });
  }

  async function handleCreate() {
    // Mirror the Send button's disabled condition (canSubmit) so the Enter-key
    // and form-submit paths that call this directly can't create a session with
    // a blank message, host, agent, or workspace.
    if (!canSubmit) return;
    setCreating(true);
    setCreateError(null);
    try {
      const trimmedBranch = branchName.trim();
      // `shouldCreateWorktree` (component scope): true only when a branch is
      // named and the workspace isn't already an existing worktree. Starting
      // in an existing worktree sends no git opts — the workspace is bound
      // straight to that dir, which also sidesteps the "branch already
      // exists" guard.
      const agent = agentList.find((a) => a.id === effectiveAgentId);
      const nativeAgent = nativeCodingAgentForAvailableAgent(agent);
      const nativeLabels = nativeWrapperLabelsForAgent(agent);
      const agentSupportsPermissionMode = nativeAgentHasCapability(agent, "permissionMode");
      const agentSupportsApprovalMode = nativeAgentHasCapability(agent, "approvalMode");
      const agentSupportsCursorMode = nativeAgentHasCapability(agent, "cursorMode");

      // Native terminal agents open terminal-first: `omnigent.ui: terminal`
      // tells the UI to render the terminal wrapper, and `omnigent.wrapper`
      // selects which CLI bridge the runner launches — the values are the
      // registered wrapper ids the runner keys off, not the display name. The
      // DANGEROUS codex full-bypass opt-in rides along as an extra label (only
      // when the toggle is armed for a codex-native agent) so the runner
      // launches with --dangerously-bypass-approvals-and-sandbox and the choice
      // survives reload.
      const baseLabels =
        agentSupportsApprovalMode && bypassSandbox
          ? { ...(nativeLabels ?? {}), [CODEX_NATIVE_BYPASS_SANDBOX_LABEL_KEY]: "1" }
          : nativeLabels;
      const createProjectId = selectedProject
        ? (selectedProjectId ?? (await resolveOrCreateProjectId(selectedProject)))
        : undefined;
      // Project sessions may carry the Project-resolved external location so
      // the existing git/worktree contract can validate before binding. An
      // unfiled session has no caller-owned location at all: the server must
      // provision an empty managed sandbox.
      const sessionLocation = selectedProject
        ? sandboxSelected
          ? { host_type: "managed" as const }
          : {
              host_id: selectedHostId,
              workspace: workspaceTrimmed,
              git: shouldCreateWorktree
                ? { branch_name: trimmedBranch, base_branch: baseBranch.trim() || undefined }
                : startInExistingWorktree
                  ? { branch_name: trimmedBranch, existing_worktree: true }
                  : undefined,
            }
        : { host_type: "managed" as const };

      let data: { id: string };

      if (effectiveAgentId === PENDING_AGENT_ID && pendingAgent) {
        // Custom agent path: build bundle client-side and use multipart POST.
        // The multipart create only stores the agent + session rows — it does
        // NOT launch a runner on the host. We must follow up with launchRunner
        // (POST /v1/hosts/{id}/runners) to bind the session to a runner, the
        // same way the fork-resume path does.
        const bundle = await buildAgentBundle(pendingAgent);
        const metadata: Record<string, unknown> = {};
        if (selectedProject && workspaceTrimmed) metadata.workspace = workspaceTrimmed;
        if (baseLabels) metadata.labels = baseLabels;
        if (createProjectId) metadata.project_id = createProjectId;
        data = await createBundledSession(
          bundle,
          metadata as Parameters<typeof createBundledSession>[1],
        );
        // Launch the runner on the selected host. The multipart create
        // only stores DB rows — launchRunner binds + starts the runner.
        if (selectedProject && !sandboxSelected && selectedHostId && workspaceTrimmed) {
          // Create a new worktree, bind an existing one (records the branch
          // for the sidebar + delete flow without creating anything), or
          // neither — mirrored on the `git` block.
          const gitOpts = shouldCreateWorktree
            ? { branchName: trimmedBranch, baseBranch: baseBranch.trim() || undefined }
            : startInExistingWorktree
              ? { branchName: trimmedBranch, existingWorktree: true }
              : undefined;
          await launchRunner(selectedHostId, data.id, workspaceTrimmed, gitOpts);
        }
        // Clear pending agent after successful creation.
        setPendingAgent(null);
      } else {
        // Normal path: bind to an existing registered agent.
        const res = await authenticatedFetch("/v1/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            agent_id: effectiveAgentId,
            ...sessionLocation,
            labels: baseLabels,
            project_id: createProjectId,
            // Permission / approval / cursor mode → CLI flag pair, persisted as
            // terminal_launch_args. Omitted for the default and non-native agents.
            terminal_launch_args:
              agentSupportsPermissionMode &&
              permissionMode !== CLAUDE_NATIVE_DEFAULT_PERMISSION_MODE
                ? ["--permission-mode", permissionMode]
                : agentSupportsApprovalMode && approvalMode !== CODEX_NATIVE_DEFAULT_APPROVAL_MODE
                  ? (CODEX_NATIVE_APPROVAL_MODES.find((m) => m.value === approvalMode)?.args ?? [])
                  : agentSupportsCursorMode && cursorExecMode !== CURSOR_NATIVE_DEFAULT_EXEC_MODE
                    ? (CURSOR_NATIVE_EXEC_MODES.find((m) => m.value === cursorExecMode)?.args ?? [])
                    : undefined,
            // Model + reasoning effort, persisted on the session row before
            // the runner launches. Claude and Codex read model_override at
            // terminal launch; an unselected ("") knob is omitted so the
            // harness keeps its own configured/default model.
            model_override:
              (agentSupportsPermissionMode || nativeAgent?.harness === "codex-native") &&
              pickedModel
                ? pickedModel
                : undefined,
            reasoning_effort:
              agentSupportsPermissionMode && pickedEffort ? pickedEffort : undefined,
            // Smart routing toggle — server-side. The "Auto" harness always
            // routes (harness + model), so send "on" to keep the persisted
            // state consistent with the lit routing icon. Otherwise only send
            // it when routing is eligible for the effective harness, so a stale
            // "on" can't ride along invisibly with no control to clear it.
            cost_control_mode_override:
              pickedHarness === AUTO_HARNESS_ID
                ? "on"
                : smartRoutingEligible
                  ? (costControlMode ?? undefined)
                  : undefined,
            harness_override: pickedHarness ?? undefined,
          }),
        });
        if (!res.ok) {
          setCreateError(await describeCreateError(res));
          return;
        }
        data = (await res.json()) as { id: string };
      }
      if (selectedProject) {
        void queryClient.invalidateQueries({ queryKey: projectQueryKeys.all });
        // Project folders own separate paginated queries and need to see the
        // newly-created, already-filed session immediately.
        void queryClient.invalidateQueries({ queryKey: projectQueryKeys.sessionsRoot });
      }
      // Fire-and-forget: don't block navigation on the sidebar list refresh.
      // The background refetch (or the WS session_added push) backfills the
      // new session's row within ~1s of landing in the chat; the chat itself
      // loads from the session id and never reads the sidebar cache.
      void queryClient.refetchQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["directory-sessions"] });
      // Prepend each "@"-tagged path as an attachment marker on its own line —
      // the same wording the native executors emit and that title-seeding
      // strips. The runner, rooted at this workspace, reads the on-disk file
      // from the marker; no upload happens. Folders carry a trailing "/".
      const initialPrompt =
        buildMentionPreamble(mentionedItems, selectedAgent?.harness ?? null) +
        sanitizeInitialPrompt(message);
      // A first message matching one of the agent's bundled skills is
      // handed off as a structured invocation so ChatPage auto-sends it
      // as a `slash_command` event (server resolves the skill) instead
      // of plain text the agent would see as a literal "/name". Native
      // terminal agents keep plain text — their CLI owns slash commands.
      setPendingInitialPrompt(data.id, {
        text: initialPrompt,
        skill: isNativeTerminalAgent
          ? null
          : matchSkillInvocation(initialPrompt, agent?.skills ?? []),
        files,
      });
      // Scope the recall entry to the new session id so ArrowUp surfaces it in
      // the freshly-opened chat (whose composer reads the same per-conversation
      // key). Sanitized text so recall reproduces exactly what was sent.
      appendPromptHistoryEntry(initialPrompt, data.id);
      // The session was created — drop the preserved draft so the next visit
      // to the landing screen starts clean (and the unmount cleanup below
      // doesn't resurrect what we just sent).
      submittedRef.current = true;
      landingDraft = null;
      navigate(`/c/${data.id}`);
    } catch {
      setCreateError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setCreating(false);
    }
  }

  return (
    // pb-12 lifts the content slightly above the geometric center, where
    // the hero reads better optically.
    <div
      ref={setLandingSurface}
      className="flex flex-1 items-center justify-center"
      data-testid="new-chat-landing"
      data-location-ready={projectLocationReady ? "true" : "false"}
    >
      {/* Padding lives inside the 840px cap, so the composer renders at
          840 − 80 = 760px max on desktop. px-4 on phones (16px gutters)
          keeps the composer from feeling cramped against the viewport
          edges; widens to the full px-10 at the md breakpoint and up. */}
      <div className="flex w-full max-w-[840px] flex-col items-center gap-8 px-4 pt-8 pb-16 md:select-none md:px-10">
        <div className="flex w-full flex-col items-center justify-center gap-3.5 sm:flex-row">
          {selectedProject ? (
            // Landing inside a project: swap Otto's eyes for a project icon
            // and name the project. Sized
            // to Otto's h-18 box so the centered composer doesn't shift when
            // toggling between the two landings.
            <span className="flex h-18 shrink-0 items-center">
              <BriefcaseBusinessIcon className="size-12 text-muted-foreground" />
            </span>
          ) : (
            <OttoEyes className="h-18 w-auto shrink-0" />
          )}
          <h1 className="min-w-0 break-words text-center text-3xl font-medium tracking-[-0.03em] text-foreground line-clamp-2 sm:text-left">
            {selectedProject || "What should we do?"}
          </h1>
        </div>
        <div className="relative flex w-full flex-col gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleCreate();
            }}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            // Two visual states only (no hover): resting --border, and
            // --foreground while the textarea itself has focus (has-[]
            // scopes it so focusing footer buttons doesn't trigger it).
            // dark:bg-card-solid: the footer tray below tucks its top
            // edge behind this card (-mt-9), and the dark glass --card
            // is 60% alpha — the tucked strip ghosts through a
            // translucent card. Mirrors the chat composer card. Drag-over
            // lifts an inset ring (overlay below).
            className={cn(
              "relative z-10 flex w-full flex-col rounded-2xl border border-border bg-card dark:bg-card-solid shadow-[0_12px_20px_-20px_rgba(0,0,0,0.14),0_20px_28px_-28px_rgba(0,0,0,0.1)] transition-[border-color,box-shadow] duration-150 has-[textarea:focus]:border-foreground",
              isDragActive && "ring-2 ring-ring ring-inset",
            )}
            data-testid="new-chat-landing-composer"
          >
            {isDragActive && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-card/80">
                <span className="text-sm font-medium text-ring">Drop files here</span>
              </div>
            )}
            {/* Skill suggestions — floats above the composer box. */}
            {slashMenuOpen && (
              <SlashCommandMenu
                query={slashMenuQuery}
                activeIndex={slashMenuIndex}
                onSelect={applySlashSelection}
                commands={skillCommands}
              />
            )}
            {/* "@"-file-mention browser — native terminal agents with a workspace */}
            {(mentionOpen || mentionListingPending) && (
              <FileMentionMenu
                currentDir={mentionDir}
                activeIndex={mentionIndex}
                entries={mentionEntries}
                loading={mentionListingPending}
                onOpenDir={openMentionDir}
                onAttach={attachMention}
              />
            )}
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => {
                setMessage(e.target.value);
                // Recompute the active "@"-mention from the caret each keystroke
                // (native terminal agents with a workspace — ``mentionEnabled``).
                setMention(
                  mentionEnabled
                    ? detectMentionAt(
                        e.target.value,
                        e.target.selectionStart ?? e.target.value.length,
                      )
                    : null,
                );
              }}
              onBlur={() => {
                // Dismiss the mention menu when focus leaves the textarea; menu
                // rows preventDefault on mousedown so selecting one doesn't blur.
                dismissMention();
              }}
              onCompositionStart={() => {
                isComposingRef.current = true;
              }}
              onCompositionEnd={() => {
                isComposingRef.current = false;
              }}
              onKeyDown={(e) => {
                if (isImeCompositionKeyEvent(e, isComposingRef.current)) {
                  return;
                }

                // "@"-mention menu navigation (shared useMentionBrowser) —
                // mutually exclusive with the slash menu (a token can't be both)
                // and takes priority over submission.
                if (handleMentionKeyDown(e)) return;

                // While the skills menu is open, ArrowUp/Down navigate it and
                // Enter/Tab complete the highlighted item — these take
                // priority over submission (same UX as the in-session
                // composer).
                if (slashMenuOpen && slashMenuMatches.length > 0) {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setSlashMenuIndex((i) => (i + 1) % slashMenuMatches.length);
                    return;
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setSlashMenuIndex((i) => (i <= 0 ? slashMenuMatches.length - 1 : i - 1));
                    return;
                  }
                  if (
                    (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) &&
                    slashMenuIndex >= 0
                  ) {
                    e.preventDefault();
                    applySlashSelection(slashMenuMatches[slashMenuIndex]!);
                    return;
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    // Dismiss the menu by clearing the draft so the user can
                    // start fresh.
                    setMessage("");
                    setSlashMenuIndex(-1);
                    return;
                  }
                }
                // Enter sends; Shift+Enter inserts a newline.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  // The mention menu is briefly closed while its listing loads;
                  // swallow Enter so the in-progress "@dir/" token isn't sent.
                  if (mentionListingPending) return;
                  void handleCreate();
                }
              }}
              onPaste={(e) => {
                // Pasted images/files attach instead of inserting as text,
                // mirroring the in-session composer.
                const pasted = Array.from(e.clipboardData.items)
                  .filter((item) => item.kind === "file")
                  .map((item) => item.getAsFile())
                  .filter((f): f is File => f !== null);
                if (pasted.length > 0) {
                  e.preventDefault();
                  addFiles(pasted);
                }
              }}
              // Suppress the native placeholder when the overlay supplies its
              // own prompt text; aria-label preserves the accessible name.
              placeholder={pillSkills.length > 0 ? "" : "Describe a task to start a new session…"}
              aria-label="Describe a task to start a new session"
              rows={1}
              autoFocus
              data-testid="new-chat-landing-input"
              // Compose-pill text spec: SF Pro Text system stack at
              // 14px/20px. (Note: sub-16px inputs make mobile Safari
              // auto-zoom on focus — accepted tradeoff per the design.)
              // Heights are border-box (16px top + 4px bottom padding lives
              // inside them): min 60px = one 20px line + a spare line of
              // breathing room; max 200px = the spec's 180px of content.
              // useAutoGrowTextarea drives the height between the two.
              className="max-h-[200px] min-h-[60px] w-full resize-none overflow-y-auto bg-transparent px-4 pt-4 pb-1 font-['SF_Pro_Text',-apple-system,BlinkMacSystemFont,system-ui,sans-serif] text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground md:select-text"
            />
            {/* Gated on an empty draft so it reads as the placeholder.
                pointer-events-none lets clicks fall through to focus the
                textarea; the pills themselves opt back in. */}
            {pillSkills.length > 0 && message.length === 0 && (
              <div className="pointer-events-none absolute inset-x-4 top-4 flex flex-wrap items-center gap-2">
                <span className="font-['SF_Pro_Text',-apple-system,BlinkMacSystemFont,system-ui,sans-serif] text-sm leading-5 text-muted-foreground">
                  Describe a task, or try a skill
                </span>
                <SkillPills skills={pillSkills} onPick={applySkillPill} />
              </div>
            )}
            {/* Hidden file input for the attach button. */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,application/pdf,text/*,application/json"
              className="hidden"
              data-testid="new-chat-landing-file-input"
              onChange={(e) => {
                if (e.target.files) {
                  addFiles(Array.from(e.target.files));
                  // Reset so the same file can be re-selected.
                  e.target.value = "";
                }
              }}
            />
            {/* "@"-mention chips — one per tagged workspace file/folder. Each is
                delivered as an "[Attached: <path>]" marker prepended to the
                first message at create time. */}
            {mentionedItems.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-4 pb-2">
                {mentionedItems.map((item, i) => (
                  <span
                    key={mentionItemPath(item)}
                    className="flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    {item.isDir ? (
                      <FolderIcon className="size-3 shrink-0" />
                    ) : (
                      <FileTextIcon className="size-3 shrink-0" />
                    )}
                    <span className="max-w-[200px] truncate" title={mentionItemPath(item)}>
                      @{item.path}
                      {item.isDir ? "/" : ""}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeMentionedItem(i)}
                      className="ml-0.5 rounded-full hover:text-foreground"
                      aria-label={`Remove ${item.path}`}
                    >
                      <XIcon className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            {/* File chips — shown below the textarea when files are attached. */}
            {files.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-4 pb-2">
                {files.map((file, i) => (
                  <span
                    key={attachmentKey(file)}
                    className="flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    {file.type.startsWith("image/") ? (
                      <ImageIcon className="size-3 shrink-0" />
                    ) : (
                      <FileTextIcon className="size-3 shrink-0" />
                    )}
                    <span className="max-w-[140px] truncate">{file.name || "image.png"}</span>
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="ml-0.5 rounded-full hover:text-foreground"
                      aria-label={`Remove ${file.name || "image.png"}`}
                    >
                      <XIcon className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            {/* No own bg — the pill paints the surface. An explicit bg-card
                here would also catch the .dark .bg-card glass rule (border +
                shadow) and visually split the pill in half. */}
            <div className="flex items-center justify-between pt-1 pr-4 pb-3 pl-2">
              {/* Attach + dictate — left side, mirroring the in-session composer. */}
              <div className="flex items-center gap-0.5">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="size-9 md:size-8"
                  disabled={creating}
                  onClick={() => fileInputRef.current?.click()}
                  title="Attach files"
                  data-testid="new-chat-landing-attach"
                >
                  <PaperclipIcon className="size-4" />
                  <span className="sr-only">Attach files</span>
                </Button>
                <ComposerMicButton
                  enableHotkey
                  disabled={creating}
                  onVoiceStart={() => {
                    voiceSnapshotRef.current = message;
                  }}
                  onVoiceDiscard={() => setMessage(voiceSnapshotRef.current)}
                  onTranscript={dictation.appendFinal}
                  onInterim={dictation.replaceInterim}
                />
              </div>
              <div className="flex items-center gap-0.5">
                {/* Agent / harness picker — selects the agent or harness only.
                  Its run-config knobs (model / effort / permission mode for
                  Claude Code, approval mode for Codex/OpenCode, exec mode for
                  Cursor, brain-harness override for bundle agents) live in the
                  gear-icon config modal beside it. */}
                <AgentHarnessPicker
                  agentEntries={agentEntries}
                  harnessEntries={harnessEntries}
                  effectiveAgentId={effectiveAgentId}
                  agentLabel={agentLabel}
                  hasAgents={agentList.length > 0}
                  host={pickerReadinessHost}
                  onSelectAgent={handleSelectAgent}
                  pendingAgent={pendingAgentAllowedOnTarget ? pendingAgent : null}
                  pendingAgentId={PENDING_AGENT_ID}
                  onSelectPending={handleSelectPending}
                  onCreateCustomAgent={() => setCreateAgentOpen(true)}
                  sandboxSelected={sandboxSelected}
                />
                {/* Gear — opens the selected agent's run-config modal. Hidden
                  when the selected agent has no knobs to configure. Hovering
                  shows the current settings so they're readable without
                  opening the modal. */}
                {selectedAgent && selectedAgentHasKnobs && (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-9 text-muted-foreground md:size-8"
                          disabled={creating}
                          onClick={() => setConfigOpen(true)}
                          data-testid="new-chat-landing-config-gear"
                        >
                          <SettingsIcon className="size-4" />
                          <span className="sr-only">Configure {selectedAgent.display_name}</span>
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent
                        side="top"
                        className="flex-col items-start gap-0.5 px-3 py-2"
                        data-testid="new-chat-landing-config-gear-tooltip"
                      >
                        {configSummary.map((row) => (
                          <span key={row.label} className="text-muted-foreground">
                            {row.label}:{" "}
                            <span className="text-popover-foreground">{row.value}</span>
                          </span>
                        ))}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
                {selectedAgent && selectedAgentHasKnobs && (
                  <HarnessConfigModal
                    open={configOpen}
                    onOpenChange={setConfigOpen}
                    agent={selectedAgent}
                    brainHarnessLabels={brainHarnessLabels}
                    host={harnessWarningHost}
                    hideUnconfigured={hideUnconfiguredHarnesses}
                    smartRoutingEligible={smartRoutingEligible}
                    permissionMode={permissionMode}
                    approvalMode={approvalMode}
                    cursorExecMode={cursorExecMode}
                    bypassSandbox={bypassSandbox}
                    pickedModel={pickedModel}
                    claudeModelOptions={claudeModelOptions}
                    claudeModelsLoading={
                      !sandboxSelected && selectedHostId !== null && hostClaudeModelsLoading
                    }
                    codexModelOptions={codexModelOptions}
                    codexModelsLoading={
                      !sandboxSelected && selectedHostId !== null && hostCodexModelsLoading
                    }
                    pickedEffort={pickedEffort}
                    pickedHarness={pickedHarness}
                    costControlMode={costControlMode}
                    setPermissionMode={setPermissionMode}
                    setApprovalMode={setApprovalMode}
                    setCursorExecMode={setCursorExecMode}
                    setBypassSandbox={setBypassSandbox}
                    setPickedModel={setPickedModel}
                    setPickedEffort={setPickedEffort}
                    setPickedHarness={handleSetPickedHarness}
                    setCostControlMode={setCostControlMode}
                  />
                )}
                {/* Smart routing is no longer a standalone composer toggle — it
                  folds into the gear modal's Model dropdown as a "Smart Routing"
                  option (see HarnessConfigModal). */}
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex">
                        <Button
                          type="submit"
                          size="icon"
                          disabled={!canSubmit}
                          aria-label={creating ? "Starting session" : "Start session"}
                          aria-busy={creating}
                          data-testid="new-chat-landing-submit"
                          className="size-8 rounded-full bg-foreground text-card transition-opacity hover:opacity-80 disabled:opacity-50"
                        >
                          {creating ? (
                            <Loader2Icon className="size-4 animate-spin" />
                          ) : (
                            <ArrowUpIcon className="size-4" />
                          )}
                        </Button>
                      </span>
                    </TooltipTrigger>
                    {submitDisabledReason != null && (
                      <TooltipContent>{submitDisabledReason}</TooltipContent>
                    )}
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
          </form>
          {/* The tray exposes only project membership and the inherited Host.
              The Host chip is intentionally read-only; changing an execution
              target belongs in Project settings. */}
          <div className="relative z-0 -mt-9 flex w-full items-center rounded-b-2xl bg-tray/40 pt-8 pr-3 pb-2 pl-2">
            <div className="flex flex-wrap items-center gap-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="flex h-6 items-center gap-1 rounded-full px-2.5 text-13 font-normal text-muted-foreground transition-colors hover:text-foreground"
                    data-testid="new-chat-landing-project-chip"
                  >
                    <BriefcaseBusinessIcon className="size-4 shrink-0" />
                    <span
                      className={`max-w-40 truncate ${selectedProject ? "text-foreground" : ""}`}
                    >
                      {selectedProject || commonT("shell.noProject")}
                    </span>
                    <ChevronDownIcon className="size-3.5 shrink-0 opacity-60" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-52">
                  <DropdownMenuItem
                    onSelect={() => selectProject("")}
                    data-testid="new-chat-landing-no-project"
                    data-active={!selectedProject ? "true" : undefined}
                    className="text-xs data-[active=true]:bg-accent/60"
                  >
                    {commonT("shell.noProject")}
                  </DropdownMenuItem>
                  {projectList && projectList.length > 0 && <DropdownMenuSeparator />}
                  {(projectList ?? []).map((project) => (
                    <DropdownMenuItem
                      key={project.id ?? `legacy:${project.name}`}
                      onSelect={() => selectProject(project.name)}
                      data-testid={`new-chat-landing-project-${project.name}`}
                      data-active={project.name === selectedProject ? "true" : undefined}
                      className="text-xs data-[active=true]:bg-accent/60"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <BriefcaseBusinessIcon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{project.name}</span>
                      </span>
                    </DropdownMenuItem>
                  ))}
                  {projectListLoading && (
                    <div className="px-2 py-1.5 text-xs text-muted-foreground">
                      {commonT("shell.loading")}
                    </div>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
              <div
                className="flex h-6 min-w-0 max-w-56 items-center gap-1 rounded-full px-2.5 text-13 font-normal text-muted-foreground"
                data-testid="new-chat-landing-host-chip"
                title={
                  selectedProject
                    ? "Execution host is inherited from Project settings"
                    : "Unfiled sessions run in a managed sandbox"
                }
              >
                {!selectedProject || sandboxSelected || projectUsesManagedWorkspace ? (
                  <MonitorCloudIcon className="size-4 shrink-0" />
                ) : (
                  <MonitorIcon className="size-4 shrink-0" />
                )}
                <span
                  className={`inline-block size-1.5 shrink-0 rounded-full ${
                    inheritedHostStatus === "online"
                      ? "bg-green-500"
                      : inheritedHostStatus === "loading"
                        ? "animate-pulse bg-muted-foreground/50"
                        : "bg-destructive"
                  }`}
                  aria-label={inheritedHostStatus}
                  data-testid="new-chat-landing-host-status"
                />
                <span className="min-w-0 truncate text-foreground">{inheritedHostLabel}</span>
              </div>
              {selectedProject && inheritedWorkspaceLabel && (
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div
                        className="flex h-6 max-w-72 items-center gap-1 rounded-full px-2.5 text-13 font-normal text-muted-foreground"
                        data-testid="new-chat-landing-workspace-chip"
                        title={projectBoundWorkspace ?? inheritedWorkspaceLabel}
                      >
                        <FolderIcon className="size-4 shrink-0" />
                        <span className="truncate text-foreground">{inheritedWorkspaceLabel}</span>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      align="start"
                      className="max-w-[min(90vw,48rem)] whitespace-normal break-all font-mono text-xs"
                      data-testid="new-chat-landing-workspace-tooltip"
                    >
                      {projectBoundWorkspace ?? inheritedWorkspaceLabel}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
            </div>
          </div>
          {/* Warn (don't block) when the selected agent's harness isn't
              configured on the selected host — the host re-checks at
              launch, so submitting surfaces a specific error if it
              really can't run. Normal-flow directly under the composer
              (like the createError line below) so it reads as part of it. */}
          {selectedAgentUnconfigured && (
            <HarnessSetupNotice
              agentName={selectedAgent?.display_name}
              hostName={harnessWarningHost?.name}
              harness={selectedAgent?.harness ?? null}
              reason={harnessUnavailableReasonOnHost(selectedAgent?.harness, harnessWarningHost)}
              featureEnabled={harnessInstallEnabled}
              onSetup={() =>
                setSetupTarget({
                  agentName: selectedAgent?.display_name,
                  harness: selectedAgent?.harness ?? null,
                  host: harnessWarningHost,
                })
              }
            />
          )}

          {/* Persistent danger banner — stays under the composer while full
              bypass is armed (the in-menu banner vanishes when the Advanced
              tray closes), so the dangerous stance is always visible before
              the session is created. Gated on the codex-native capability so
              a stale toggle from a since-switched agent can't show it. */}
          {supportsApprovalMode && bypassSandbox && (
            <p
              role="alert"
              className="flex items-center gap-1.5 rounded-md border border-destructive bg-destructive/10 px-2 py-1.5 text-xs font-medium text-destructive"
              data-testid="new-chat-landing-bypass-sandbox-active-banner"
            >
              <TriangleAlertIcon className="size-3.5 shrink-0" />
              <span>
                Codex will run with approvals and the sandbox disabled — it can edit any file and
                run any command without asking.
              </span>
            </p>
          )}

          {createError && (
            <p className="text-xs text-destructive" data-testid="new-chat-landing-error">
              {createError}
            </p>
          )}
        </div>
      </div>

      {/* Harness "Set up" dialog — the single home for install/login (and later
          API key / gateway) setup, opened from the composer notice or a picker
          row's "Set up →". */}
      <HarnessSetupDialog
        open={setupTarget !== null}
        onOpenChange={(open) => {
          if (!open) setSetupTarget(null);
        }}
        agentName={setupTarget?.agentName}
        harness={setupTarget?.harness ?? null}
        host={setupTarget?.host}
      />

      {/* Create custom agent dialog — opened from the agent picker dropdown. */}
      <CreateAgentDialog
        open={createAgentOpen}
        onOpenChange={setCreateAgentOpen}
        onCreate={(input) => {
          setPendingAgent(input);
          setPickedAgentId(PENDING_AGENT_ID);
          setPickedHarness(null);
        }}
      />
    </div>
  );
}
