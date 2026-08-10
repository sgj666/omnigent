import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import {
  AgentBundleApiError,
  AgentVersionConflict,
  type AgentActivity,
  type AgentBundleDraft,
} from "@/lib/multiAgentApi";
import { MultiAgentDetailPage } from "./MultiAgentDetailPage";

const hooks = vi.hoisted(() => ({
  detail: vi.fn(),
  activity: vi.fn(),
  schema: vi.fn(),
  options: vi.fn(),
  hostModels: vi.fn(),
  create: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
  update: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
  feishuConnection: vi.fn(),
  feishuSurfaceProfile: {
    data: {
      details_enabled: true,
      details_base_url: "http://127.0.0.1:5173",
      actions: ["quick_commands", "manage_devices", "switch_workspace"],
    },
    error: null,
  },
}));

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgent: () => hooks.detail(),
  useAgentActivity: () => hooks.activity(),
  useAgentFormSchema: () => hooks.schema(),
  useAgentBundleOptions: () => hooks.options(),
  useCreateMultiAgent: () => hooks.create,
  useUpdateMultiAgent: () => hooks.update,
}));

vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({
    data: [
      {
        id: "ws_1",
        root_path: "/work/project",
        repositories: [
          { name: "api", path: "/work/project/api" },
          { name: "web", path: "/work/project/web" },
        ],
      },
    ],
    isLoading: false,
    isError: false,
  }),
  useCreateWorkspace: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({ data: [{ host_id: "host_1", name: "Local Mac", status: "online" }] }),
  useHostModelOptions: (...args: unknown[]) => hooks.hostModels(...args),
}));

vi.mock("@/hooks/useFeishuInstall", () => ({
  useAgentFeishuConnection: () => hooks.feishuConnection(),
  useBeginAgentFeishu: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useDisconnectAgentFeishu: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useBindAgentFeishuWorkspace: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useAgentFeishuSurface: () => ({ data: undefined, error: null }),
  useAgentFeishuSurfaceProfile: () => hooks.feishuSurfaceProfile,
  useReinitializeAgentFeishuSurface: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
  }),
  useAgentDefaultWorkspaceScope: () => ({ data: null, error: null }),
  useSetAgentDefaultWorkspaceScope: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useSetAgentFeishuSurfaceProfile: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
}));

const draft: AgentBundleDraft = {
  card: {
    id: "ag_custom",
    name: "My bundle",
    description: "Coordinator and reviewer",
    harness: "codex-native",
    worker_count: 1,
    skill_count: 0,
    mcp_count: 0,
    version: 3,
    digest: "sha256:abcdef",
    readonly: false,
    updated_at: 1_786_000_000,
    builtin: false,
    editable: true,
    validation_status: "invalid",
  },
  version: 3,
  digest: "sha256:abcdef",
  files: [],
  coordinator: {
    path: "config.yaml",
    content: "name: My bundle\nunknown: keep # comment\n",
    data: {
      name: "My bundle",
      executor: { config: { harness: "codex-native" } },
      prompt: "Coordinate the work",
      async: true,
      timers: false,
      spawn: true,
      unknown: "keep",
    },
  },
  workers: [
    {
      path: "agents/reviewer/config.yaml",
      content: "name: reviewer\n",
      data: { name: "reviewer", prompt: "Review changes" },
    },
  ],
  diagnostics: [
    {
      severity: "error",
      code: "invalid_yaml",
      file: "config.yaml",
      path: "/guardrails",
      line: 9,
      column: 4,
      message: "Guardrail is invalid",
    },
  ],
  schema_version: "1",
};

function copyDraft() {
  return structuredClone(draft);
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/multi-agents/ag_custom"]}>
        <Routes>
          <Route path="/multi-agents/:agentId" element={<MultiAgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderCreatePage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/multi-agents/new"]}>
        <Routes>
          <Route path="/multi-agents/:agentId" element={<MultiAgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function selectTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0, ctrlKey: false });
}

describe("MultiAgentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const data = copyDraft();
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.activity.mockReturnValue({
      data: {
        agent_id: "ag_custom",
        total_runs: 0,
        active_runs: 0,
        waiting_runs: 0,
        failed_runs: 0,
        success_rate: null,
        recent_runs: [],
        projects: [],
        skills: [],
        skill_usage_source: "observed_load_skill_calls",
      } satisfies AgentActivity,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    hooks.schema.mockReturnValue({ data: { schema_version: "1", fields: [] } });
    hooks.options.mockReturnValue({
      data: {
        harnesses: [{ id: "provider-harness", label: "Provider Harness" }],
        models: [],
        tools: [],
        skills: [],
        mcp: [],
        environment: [],
      },
    });
    hooks.hostModels.mockReturnValue({ data: [], isLoading: false, isError: false });
    hooks.create.mutateAsync.mockResolvedValue(data);
    hooks.update.mutateAsync.mockResolvedValue({ ...data, version: data.version + 1 });
    hooks.feishuConnection.mockReturnValue({ data: null, isLoading: false, error: null });
  });

  it("requires a provider-owned harness when creating a bundle", async () => {
    renderCreatePage();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Approval agent" } });
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();

    fireEvent.pointerDown(screen.getByLabelText("Harness"), {
      button: 0,
      pointerType: "mouse",
    });
    fireEvent.click(screen.getByRole("option", { name: "Provider Harness" }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(hooks.create.mutateAsync).toHaveBeenCalledWith({
        name: "Approval agent",
        description: undefined,
        config: {
          spec_version: 1,
          name: "Approval agent",
          executor: { type: "omnigent", config: { harness: "provider-harness" } },
        },
      }),
    );
  });

  it("renders the visual editor without pinning a local-default model", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "My bundle" })).toBeVisible();
    expect(screen.getByLabelText("Model")).toHaveTextContent("Use local default");
    expect(screen.getAllByText("Use local default")).not.toHaveLength(0);
    expect(screen.getByRole("tab", { name: "Visual" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Advanced YAML" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getByText("Not connected")).toBeVisible();
  });

  it("selects repository Skills and preserves configured names missing from the inventory", async () => {
    const data = copyDraft();
    const coordinatorConfig = data.coordinator!.data;
    if (
      coordinatorConfig === null ||
      typeof coordinatorConfig !== "object" ||
      Array.isArray(coordinatorConfig)
    ) {
      throw new Error("test coordinator config must be an object");
    }
    coordinatorConfig.skills = ["removed-skill"];
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.options.mockReturnValue({
      data: {
        harnesses: [{ id: "provider-harness", label: "Provider Harness" }],
        models: [],
        tools: [],
        skills: [
          {
            id: "skill-1",
            name: "proposal",
            description: "Create a scoped proposal.",
            relative_path: "skills/common/proposal",
            validation_status: "valid",
          },
        ],
        mcp: [],
        environment: [],
      },
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Advanced properties/ }));

    expect(screen.getByText("removed-skill")).toBeVisible();
    expect(screen.getByText("Unavailable")).toBeVisible();
    fireEvent.click(screen.getByRole("combobox", { name: "Allowed skill names" }));
    fireEvent.click(await screen.findByText("proposal"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "replace",
      path: "/skills",
      value: ["removed-skill", "proposal"],
    });
  });

  it("renders real Agent activity with TaskRun, Session, Project, reason, and Skill links", () => {
    hooks.activity.mockReturnValue({
      data: {
        agent_id: "ag_custom",
        total_runs: 3,
        active_runs: 1,
        waiting_runs: 1,
        failed_runs: 1,
        success_rate: 0.5,
        recent_runs: [
          {
            id: "run-success-1234",
            task_id: "task-1",
            task_title: "Publish launch report",
            state: "succeeded",
            queued_at: 1_786_000_000,
            started_at: 1_786_000_001,
            finished_at: 1_786_000_010,
            session_id: "session-1",
            runtime_id: "host-1",
            workspace: "/work/project",
            project_id: "project-1",
            project_name: "Launch",
            waiting_reason: null,
            failure_code: null,
            failure_message: null,
          },
          {
            id: "run-wait-1234",
            task_id: "task-2",
            task_title: "Approve release",
            state: "waiting",
            queued_at: 1_785_999_000,
            started_at: 1_785_999_001,
            finished_at: null,
            session_id: "session-2",
            runtime_id: "host-1",
            workspace: "/work/project",
            project_id: null,
            project_name: null,
            waiting_reason: "Awaiting approval",
            failure_code: null,
            failure_message: null,
          },
          {
            id: "run-fail-1234",
            task_id: "task-3",
            task_title: "Check deployment",
            state: "failed",
            queued_at: 1_785_998_000,
            started_at: 1_785_998_001,
            finished_at: 1_785_998_010,
            session_id: "session-3",
            runtime_id: "host-1",
            workspace: "/work/project",
            project_id: "project-1",
            project_name: "Launch",
            waiting_reason: null,
            failure_code: "runner_error",
            failure_message: "Runner stopped",
          },
        ],
        projects: [{ id: "project-1", name: "Launch", run_count: 2 }],
        skills: [{ name: "cross-review", uses: 2 }],
        skill_usage_source: "observed_load_skill_calls",
      } satisfies AgentActivity,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    renderPage();

    expect(screen.getByTestId("agent-activity")).toHaveTextContent("50%");
    expect(screen.getByText("Awaiting approval")).toBeVisible();
    expect(screen.getByText("Runner stopped")).toBeVisible();
    expect(screen.getByText("runner_error")).toBeVisible();
    expect(screen.getByText("cross-review")).toBeVisible();
    expect(screen.getByRole("link", { name: "Publish launch report" })).toHaveAttribute(
      "href",
      "/tasks/task-1#run-run-success-1234",
    );
    expect(screen.getAllByRole("link", { name: "Session session-" })[0]).toHaveAttribute(
      "href",
      "/c/session-1",
    );
    expect(screen.getAllByRole("link", { name: "Launch" })[0]).toHaveAttribute(
      "href",
      "/projects/project-1",
    );
  });

  it("selects a model from the online Host catalog and keeps the prompt compact", async () => {
    hooks.hostModels.mockReturnValue({
      data: [
        {
          id: "sonnet",
          model: "provider-model",
          displayName: "Sonnet",
        },
      ],
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(hooks.hostModels).toHaveBeenLastCalledWith("host_1", "codex-native", true);
    expect(screen.getByLabelText("Prompt")).toHaveClass(
      "h-44",
      "min-h-32",
      "resize-y",
      "overflow-y-auto",
    );
    fireEvent.pointerDown(screen.getByLabelText("Model"), {
      button: 0,
      pointerType: "mouse",
    });
    fireEvent.click(screen.getByText("Sonnet"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "add",
      path: "/executor/model",
      value: "provider-model",
    });
  });

  it("surfaces structured diagnostics without mixing run controls into the editor", () => {
    renderPage();

    expect(screen.getByText("config.yaml:9:4 · /guardrails")).toBeVisible();
    expect(screen.getByText("Guardrail is invalid")).toBeVisible();
    expect(screen.queryByText("Workspace & run")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
  });

  it("opens Agent-scoped Feishu pairing instead of completing from a status-only button", () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Connect Feishu" }));

    expect(screen.getByRole("dialog", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getByText("Coordinator connection")).toBeVisible();
  });

  it("shows the persisted Feishu connection and rebinding action", () => {
    hooks.feishuConnection.mockReturnValue({
      data: { status: "connected", bot_name: "Omnigent Assistant" },
      isLoading: false,
      error: null,
    });

    renderPage();

    expect(screen.getByText(/Connected to Feishu/)).toBeVisible();
    expect(screen.getByText(/Omnigent Assistant/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Change Feishu binding" }));
    expect(screen.getByRole("dialog", { name: "Manage Feishu connection" })).toBeVisible();
  });

  it("renders schema-only fields and preserves tri-state defaults", async () => {
    const data = copyDraft();
    data.coordinator!.data = {
      name: "My bundle",
      executor: { config: { harness: "codex-native" } },
      prompt: "Coordinate the work",
      interaction: { mode: "chat" },
      unknown: "keep",
    };
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.schema.mockReturnValue({
      data: {
        schema_version: "1",
        fields: [
          {
            path: "/interaction",
            type: "object",
            group: "advanced",
            required: false,
            secret: false,
            translation_key: "multiAgent.fields.interaction",
            editor: "generic-tree",
          },
        ],
      },
    });

    renderPage();

    expect(screen.getByLabelText("Async dispatch")).toHaveTextContent("Default");
    expect(screen.getByLabelText("Timers")).toHaveTextContent("Default");
    expect(screen.getByLabelText("Spawn child sessions")).toHaveTextContent("Default");
    fireEvent.click(screen.getByRole("button", { name: /Advanced properties/ }));
    expect(screen.queryByLabelText("/interaction")).toBeNull();
    expect(screen.getAllByText(/conversation protocol/i)).not.toHaveLength(0);
    fireEvent.change(screen.getByLabelText("mode"), { target: { value: "guided" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "replace",
      path: "/interaction",
      value: { mode: "guided" },
    });
  });

  it("renders nested executor fields and preserves siblings on a single-field save", async () => {
    const data = copyDraft();
    data.coordinator!.data = {
      name: "My bundle",
      executor: {
        type: "provider",
        model: "model-1",
        context_window: 128000,
        auth: "existing-secret",
        config: { harness: "codex-native", provider_region: "us-east", retries: 2 },
      },
    };
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.schema.mockReturnValue({
      data: {
        schema_version: "1",
        fields: [
          "/executor/type",
          "/executor/context_window",
          "/executor/config",
          "/executor/auth",
        ].map((path) => ({
          path,
          type:
            path === "/executor/context_window"
              ? "integer"
              : path === "/executor/config" || path === "/executor/auth"
                ? "object"
                : "string",
          group: "executor",
          required: false,
          secret: path === "/executor/auth",
          translation_key: path,
          editor: "generic-tree",
        })),
      },
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Advanced properties/ }));

    expect(screen.queryByLabelText("/executor/type")).toBeNull();
    expect(screen.getByLabelText("/executor/context_window")).toHaveValue(128000);
    expect(screen.getByLabelText("provider_region")).toHaveValue("us-east");
    expect(screen.getByLabelText("retries")).toHaveValue(2);
    expect(screen.getByLabelText("/executor/auth")).toHaveValue("");
    expect(screen.getByLabelText("/executor/auth")).toHaveAttribute(
      "placeholder",
      "Configured — enter a new value to replace it",
    );

    fireEvent.change(screen.getByLabelText("/executor/context_window"), {
      target: { value: "64000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toEqual([
      {
        file: "config.yaml",
        op: "replace",
        path: "/executor/context_window",
        value: 64000,
      },
    ]);
  });

  it("uses guided controls for advanced settings without exposing JSON", async () => {
    const data = copyDraft();
    data.coordinator!.data = {
      name: "My bundle",
      executor: { type: "provider", config: { harness: "codex-native" } },
      tools: {
        agents: ["reviewer"],
        builtins: null,
        timeout: null,
        retry: null,
      },
      os_env: {
        type: "caller_process",
        cwd: ".",
        sandbox: { type: "none" },
      },
      guardrails: {
        policies: {
          blast_radius: {
            on: ["tool_call"],
            function: {
              path: "omnigent.guardrails.blast_radius",
              arguments: { gate_pushes: true },
            },
          },
        },
      },
      policies: { top_level_policy: { enabled: true } },
    };
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.schema.mockReturnValue({
      data: {
        schema_version: "1",
        fields: [
          {
            path: "/spec_version",
            type: "string",
            group: "advanced",
            required: false,
            secret: false,
            translation_key: "/spec_version",
            editor: "text",
          },
          {
            path: "/executor/type",
            type: "string",
            group: "executor",
            required: false,
            secret: false,
            translation_key: "/executor/type",
            editor: "text",
          },
        ],
      },
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Advanced properties/ }));

    expect(screen.getByText("Callable teammates")).toBeVisible();
    const teammateButton = screen
      .getAllByRole("button", { name: "reviewer" })
      .find((button) => button.hasAttribute("aria-pressed"));
    expect(teammateButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Built-in tools")).toBeNull();
    expect(screen.queryByText("Tool timeout")).toBeNull();
    expect(screen.queryByText("Failure retries")).toBeNull();
    expect(screen.getByText("Execution mode")).toBeVisible();
    expect(screen.getByText("Working directory")).toBeVisible();
    expect(screen.getByText("OS isolation")).toBeVisible();
    expect(screen.getByText("Isolation mode")).toBeVisible();
    expect(screen.getByText("Trigger")).toBeVisible();
    expect(screen.getByText("Function path")).toBeVisible();
    expect(screen.getByText("Gate pushes")).toBeVisible();
    expect(screen.queryByLabelText("/spec_version")).toBeNull();
    expect(screen.queryByLabelText("/executor/type")).toBeNull();
    expect(screen.queryByText("top_level_policy")).toBeNull();
    expect(screen.queryByDisplayValue(/\{\s*"agents"/)).toBeNull();

    fireEvent.click(teammateButton!);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "replace",
      path: "/tools",
      value: {
        agents: [],
        builtins: null,
        timeout: null,
        retry: null,
      },
    });
  });

  it("keeps non-inline files visible in the file tree", () => {
    const data = copyDraft();
    data.files.push({
      path: "notes/large.yaml",
      content: null,
      size: 1_048_577,
      inline: false,
    });
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();
    selectTab("Advanced YAML");
    fireEvent.click(screen.getByRole("button", { name: "notes/large.yaml" }));

    expect(screen.getByText(/too large to edit inline \(1048577 bytes\)/i)).toBeVisible();
    expect(screen.queryByLabelText("notes/large.yaml")).toBeNull();
  });

  it("confirms referenced worker deletion with the same version and exact references", async () => {
    const data = copyDraft();
    data.workers.unshift({
      path: "agents/unreferenced/config.yaml",
      content: "name: unreferenced\n",
      data: { name: "unreferenced" },
    });
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
    hooks.update.mutateAsync
      .mockRejectedValueOnce(
        new AgentBundleApiError("Referenced worker", 400, "invalid_bundle", [
          {
            severity: "error",
            code: "worker_references_require_confirmation",
            file: "agents/critic/config.yaml",
            path: "/delegate_to",
            line: null,
            column: null,
            message: "worker is referenced",
            worker: "reviewer",
          },
        ]),
      )
      .mockResolvedValueOnce({ ...data, version: 4, workers: [] });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Remove worker unreferenced" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove worker reviewer" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("agents/critic/config.yaml#/delegate_to")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Confirm worker deletion" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2));
    expect(hooks.update.mutateAsync.mock.calls[1][0].request).toMatchObject({
      expected_version: 3,
      worker_operations: [
        {
          op: "delete",
          name: "unreferenced",
        },
        {
          op: "delete",
          name: "reviewer",
          confirmed_references: ["agents/critic/config.yaml#/delegate_to"],
        },
      ],
    });
  });

  it("renders provider-owned harness options instead of a hard-coded catalog", () => {
    renderPage();

    fireEvent.pointerDown(screen.getByLabelText("Harness"), {
      button: 0,
      pointerType: "mouse",
    });

    expect(screen.getByText("Provider Harness")).toBeVisible();
    expect(screen.queryByText("opencode-native")).toBeNull();
  });

  it("lets a new worker be configured before the bundle is saved", async () => {
    const created = copyDraft();
    created.version = 4;
    created.card.version = 4;
    created.workers.push({
      path: "agents/writer/config.yaml",
      content: "name: writer\n",
      data: { name: "writer" },
    });
    hooks.update.mutateAsync.mockReset();
    hooks.update.mutateAsync.mockResolvedValueOnce(created).mockResolvedValueOnce(created);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add worker" }));

    expect(screen.getByLabelText("Name")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "writer" } });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Writes the final answer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2));
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.worker_operations).toEqual([
      { op: "add", name: "writer", source: "minimal" },
    ]);
    expect(hooks.update.mutateAsync.mock.calls[1][0].request.patches).toContainEqual({
      file: "agents/writer/config.yaml",
      op: "add",
      path: "/description",
      value: "Writes the final answer",
    });
  });

  it("does not let an Advanced YAML edit overwrite an unsaved Visual edit", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Unsaved visual description" },
    });
    selectTab("Advanced YAML");

    expect(screen.getByLabelText("config.yaml")).toBeDisabled();
    expect(screen.getByText(/save or reload the visual changes/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "add",
      path: "/description",
      value: "Unsaved visual description",
    });
  });

  it("keeps a valid YAML edit and layers narrow visual patches over its parsed data", async () => {
    renderPage();
    selectTab("Advanced YAML");
    const source = "name: My bundle\ndescription: From YAML\nunknown: keep # comment\n";
    fireEvent.change(screen.getByLabelText("config.yaml"), { target: { value: source } });
    selectTab("Visual");

    expect(screen.getByLabelText("Description")).toHaveValue("From YAML");
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "From Visual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    const patches = hooks.update.mutateAsync.mock.calls[0][0].request.patches;
    expect(patches).toContainEqual({ file: "config.yaml", op: "replace_file", value: source });
    expect(patches).toContainEqual({
      file: "config.yaml",
      op: "replace",
      path: "/description",
      value: "From Visual",
    });
  });

  it("preserves worker reordering after parsing an Advanced YAML edit", async () => {
    const data = copyDraft();
    data.coordinator!.content =
      "name: My bundle\ntools:\n  agents:\n    - reviewer\n    - writer\n";
    data.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["reviewer", "writer"] },
    };
    data.workers.push({
      path: "agents/writer/config.yaml",
      content: "name: writer\n",
      data: { name: "writer" },
    });
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();
    selectTab("Advanced YAML");
    const source =
      "name: My bundle\ndescription: YAML edit\ntools:\n  agents:\n    - reviewer\n    - writer\n";
    fireEvent.change(screen.getByLabelText("config.yaml"), { target: { value: source } });
    fireEvent.click(screen.getByRole("button", { name: "Move down reviewer" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "replace",
      path: "/tools/agents",
      value: ["writer", "reviewer"],
    });
  });

  it("persists the visible order when a pending worker is moved before save", async () => {
    const first = copyDraft();
    first.version = 4;
    first.card.version = 4;
    first.workers.push({
      path: "agents/worker-2/config.yaml",
      content: "name: worker-2\n",
      data: { name: "worker-2" },
    });
    first.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["reviewer", "worker-2"] },
    };
    const reordered = copyDraft();
    reordered.version = 5;
    reordered.card.version = 5;
    reordered.workers = [first.workers[1], first.workers[0]];
    reordered.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["worker-2", "reviewer"] },
    };
    hooks.update.mutateAsync.mockReset();
    hooks.update.mutateAsync.mockResolvedValueOnce(first).mockResolvedValueOnce(reordered);

    const page = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add worker" }));
    fireEvent.click(screen.getByRole("button", { name: "Move up worker-2" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2));
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.worker_operations).toEqual([
      { op: "add", name: "worker-2", source: "minimal" },
    ]);
    expect(hooks.update.mutateAsync.mock.calls[1][0]).toEqual({
      agent_id: "ag_custom",
      request: {
        expected_version: 4,
        patches: [
          {
            file: "config.yaml",
            op: "replace",
            path: "/tools/agents",
            value: ["worker-2", "reviewer"],
          },
        ],
      },
    });

    hooks.detail.mockReturnValue({ data: reordered, isLoading: false, isError: false });
    page.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/multi-agents/ag_custom"]}>
          <Routes>
            <Route path="/multi-agents/:agentId" element={<MultiAgentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => {
      const workerButtons = screen.getAllByRole("button", { name: /worker-2|reviewer/ });
      expect(
        workerButtons.findIndex((button) => button.getAttribute("aria-label") === "worker-2"),
      ).toBeLessThan(
        workerButtons.findIndex((button) => button.getAttribute("aria-label") === "reviewer"),
      );
    });
  });

  it("resumes only the pending worker order after a failed second phase and refetch", async () => {
    const first = copyDraft();
    first.version = 4;
    first.card.version = 4;
    first.digest = "sha256:first-phase";
    first.card.digest = "sha256:first-phase";
    first.workers.push({
      path: "agents/worker-2/config.yaml",
      content: "name: worker-2\n",
      data: { name: "worker-2" },
    });
    first.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["reviewer", "worker-2"] },
    };
    const reordered = structuredClone(first);
    reordered.version = 5;
    reordered.card.version = 5;
    reordered.digest = "sha256:ordered";
    reordered.card.digest = "sha256:ordered";
    reordered.workers = [first.workers[1], first.workers[0]];
    reordered.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["worker-2", "reviewer"] },
    };
    hooks.update.mutateAsync.mockReset();
    hooks.update.mutateAsync
      .mockResolvedValueOnce(first)
      .mockRejectedValueOnce(new Error("order save failed"))
      .mockResolvedValueOnce(reordered);

    const page = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add worker" }));
    fireEvent.click(screen.getByRole("button", { name: "Move up worker-2" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2));
    expect(screen.getByText("order save failed")).toBeVisible();

    hooks.detail.mockReturnValue({ data: first, isLoading: false, isError: false });
    page.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/multi-agents/ag_custom"]}>
          <Routes>
            <Route path="/multi-agents/:agentId" element={<MultiAgentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("button", { name: /^(worker-2|reviewer)$/ })
          .map((button) => button.getAttribute("aria-label")),
      ).toEqual(["worker-2", "reviewer"]),
    );

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(3));
    expect(hooks.update.mutateAsync.mock.calls[2][0]).toEqual({
      agent_id: "ag_custom",
      request: {
        expected_version: 4,
        patches: [
          {
            file: "config.yaml",
            op: "replace",
            path: "/tools/agents",
            value: ["worker-2", "reviewer"],
          },
        ],
      },
    });
    expect(
      hooks.update.mutateAsync.mock.calls.filter(
        ([variables]) => variables.request.worker_operations !== undefined,
      ),
    ).toHaveLength(1);
  });

  it("stops retrying a stale order CAS and reloads the latest server bundle", async () => {
    const first = copyDraft();
    first.version = 4;
    first.card.version = 4;
    first.digest = "sha256:first-phase";
    first.card.digest = "sha256:first-phase";
    first.workers.push({
      path: "agents/worker-2/config.yaml",
      content: "name: worker-2\n",
      data: { name: "worker-2" },
    });
    first.coordinator!.data = {
      name: "My bundle",
      tools: { agents: ["reviewer", "worker-2"] },
    };
    const latest = structuredClone(first);
    latest.version = 5;
    latest.card.version = 5;
    latest.digest = "sha256:concurrent";
    latest.card.digest = "sha256:concurrent";
    const refetch = vi.fn().mockResolvedValue({ data: latest });
    hooks.update.mutateAsync.mockReset();
    hooks.update.mutateAsync
      .mockResolvedValueOnce(first)
      .mockRejectedValueOnce(
        new AgentVersionConflict("Agent bundle changed", 4, 5, [], "version_conflict"),
      );

    const page = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Add worker" }));
    fireEvent.click(screen.getByRole("button", { name: "Move up worker-2" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/server bundle changed to version 5/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(hooks.update.mutateAsync).toHaveBeenCalledTimes(2);

    hooks.detail.mockReturnValue({ data: latest, isLoading: false, isError: false, refetch });
    page.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/multi-agents/ag_custom"]}>
          <Routes>
            <Route path="/multi-agents/:agentId" element={<MultiAgentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(
      screen
        .getAllByRole("button", { name: /^(worker-2|reviewer)$/ })
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["worker-2", "reviewer"]);

    fireEvent.click(screen.getByRole("button", { name: "Reload server version" }));
    await waitFor(() => expect(refetch).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("button", { name: /^(worker-2|reviewer)$/ })
          .map((button) => button.getAttribute("aria-label")),
      ).toEqual(["reviewer", "worker-2"]),
    );
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Editable after reload" },
    });
    expect(screen.getByLabelText("Description")).toHaveValue("Editable after reload");
  });

  it("preserves invalid YAML with a location diagnostic and blocks saving", () => {
    renderPage();
    selectTab("Advanced YAML");
    const editor = screen.getByLabelText("config.yaml");

    fireEvent.change(editor, { target: { value: "name My bundle\n" } });

    expect(editor).toHaveValue("name My bundle\n");
    expect(screen.getByText(/line 1, column 1/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(hooks.update.mutateAsync).not.toHaveBeenCalled();
  });

  it("edits a safe instructions file by its real bundle path", async () => {
    const data = copyDraft();
    data.coordinator!.content = "name: My bundle\ninstructions: AGENTS.md\n";
    data.coordinator!.data = { name: "My bundle", instructions: "AGENTS.md" };
    data.files = [data.coordinator!, { path: "AGENTS.md", content: "Coordinate from file\n" }];
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();

    expect(screen.getByLabelText("Prompt")).toHaveValue("Coordinate from file\n");
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Updated file prompt\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    const patches = hooks.update.mutateAsync.mock.calls[0][0].request.patches;
    expect(patches).toContainEqual({
      file: "AGENTS.md",
      op: "replace_file",
      value: "Updated file prompt\n",
    });
    expect(patches).not.toContainEqual(expect.objectContaining({ path: "/prompt" }));
  });

  it("gives dirty Visual prompts ownership of coordinator and worker instructions files", async () => {
    const data = copyDraft();
    data.coordinator!.content = "name: My bundle\ninstructions: AGENTS.md\n";
    data.coordinator!.data = { name: "My bundle", instructions: "AGENTS.md" };
    data.workers[0].content = "name: reviewer\ninstructions: AGENTS.md\n";
    data.workers[0].data = { name: "reviewer", instructions: "AGENTS.md" };
    data.files = [
      data.coordinator!,
      data.workers[0],
      { path: "AGENTS.md", content: "Coordinate from file\n" },
      { path: "agents/reviewer/AGENTS.md", content: "Review from file\n" },
    ];
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();
    selectTab("Advanced YAML");
    fireEvent.click(screen.getByRole("button", { name: "AGENTS.md" }));
    fireEvent.change(screen.getByLabelText("AGENTS.md"), {
      target: { value: "Raw coordinator edit\n" },
    });
    selectTab("Visual");
    fireEvent.click(screen.getByRole("button", { name: "My bundle" }));
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Visual coordinator edit\n" },
    });

    selectTab("Advanced YAML");
    fireEvent.click(screen.getByRole("button", { name: "AGENTS.md" }));
    expect(screen.getByLabelText("AGENTS.md")).toBeDisabled();
    expect(screen.getByText(/save or reload the visual changes/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "agents/reviewer/AGENTS.md" }));
    fireEvent.change(screen.getByLabelText("agents/reviewer/AGENTS.md"), {
      target: { value: "Raw worker edit\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "reviewer" }));
    selectTab("Visual");
    fireEvent.change(screen.getByLabelText("Prompt"), {
      target: { value: "Visual worker edit\n" },
    });

    selectTab("Advanced YAML");
    fireEvent.click(screen.getByRole("button", { name: "agents/reviewer/AGENTS.md" }));
    expect(screen.getByLabelText("agents/reviewer/AGENTS.md")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    const patches = hooks.update.mutateAsync.mock.calls[0][0].request.patches;
    expect(patches.filter((entry: { file: string }) => entry.file === "AGENTS.md")).toEqual([
      { file: "AGENTS.md", op: "replace_file", value: "Visual coordinator edit\n" },
    ]);
    expect(
      patches.filter((entry: { file: string }) => entry.file === "agents/reviewer/AGENTS.md"),
    ).toEqual([
      {
        file: "agents/reviewer/AGENTS.md",
        op: "replace_file",
        value: "Visual worker edit\n",
      },
    ]);
  });

  it("shows and edits non-config text files in the complete file tree", async () => {
    const data = copyDraft();
    data.files = [
      data.coordinator!,
      data.workers[0],
      { path: "notes/context.txt", content: "exact notes\n" },
    ];
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();
    selectTab("Advanced YAML");
    fireEvent.click(screen.getByRole("button", { name: "notes/context.txt" }));
    const editor = screen.getByLabelText("notes/context.txt");
    expect(editor).toHaveValue("exact notes\n");
    fireEvent.change(editor, { target: { value: "updated notes\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "notes/context.txt",
      op: "replace_file",
      value: "updated notes\n",
    });
  });

  it("does not resolve dangerous instructions paths", () => {
    const data = copyDraft();
    data.coordinator!.data = { name: "My bundle", instructions: "../secret.md" };
    data.files = [data.coordinator!, { path: "secret.md", content: "must not leak into prompt" }];
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });

    renderPage();

    expect(screen.getByLabelText("Prompt")).toHaveValue("../secret.md");
    expect(screen.getByLabelText("Prompt")).not.toHaveValue("must not leak into prompt");
  });

  it("preserves the current draft across a language switch", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Unsaved name" } });

    try {
      await act(() => i18n.changeLanguage("zh-CN"));
      expect(screen.getByLabelText("名称")).toHaveValue("Unsaved name");
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});
