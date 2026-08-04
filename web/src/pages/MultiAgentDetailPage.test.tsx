import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import {
  AgentBundleApiError,
  AgentVersionConflict,
  type AgentBundleDraft,
} from "@/lib/multiAgentApi";
import { MultiAgentDetailPage } from "./MultiAgentDetailPage";

const hooks = vi.hoisted(() => ({
  detail: vi.fn(),
  schema: vi.fn(),
  options: vi.fn(),
  create: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
  update: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
}));

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgent: () => hooks.detail(),
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
}));

vi.mock("@/hooks/useFeishuInstall", () => ({
  useAgentFeishuConnection: () => ({ data: null, isLoading: false, error: null }),
  useBeginAgentFeishu: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useDisconnectAgentFeishu: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useBindAgentFeishuWorkspace: () => ({ mutateAsync: vi.fn(), isPending: false, error: null }),
  useAgentFeishuSurface: () => ({ data: undefined, error: null }),
  useReinitializeAgentFeishuSurface: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
    error: null,
  }),
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

function selectTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0, ctrlKey: false });
}

describe("MultiAgentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const data = copyDraft();
    hooks.detail.mockReturnValue({ data, isLoading: false, isError: false });
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
    hooks.update.mutateAsync.mockResolvedValue({ ...data, version: data.version + 1 });
  });

  it("renders the visual editor without pinning a local-default model", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "My bundle" })).toBeVisible();
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText("Use local default")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Visual" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Advanced YAML" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getByText("Not connected")).toBeVisible();
  });

  it("surfaces structured diagnostics and workspace repositories", () => {
    renderPage();

    expect(screen.getByText("config.yaml:9:4 · /guardrails")).toBeVisible();
    expect(screen.getByText("Guardrail is invalid")).toBeVisible();
    expect(screen.getByText("/work/project")).toBeVisible();
    expect(screen.getByText("api")).toBeVisible();
    expect(screen.getByText("web")).toBeVisible();
    expect(screen.getByRole("button", { name: "Run" })).toBeVisible();
  });

  it("opens Agent-scoped Feishu pairing instead of completing from a status-only button", () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Connect Feishu" }));

    expect(screen.getByRole("dialog", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getByText("Coordinator connection")).toBeVisible();
  });

  it("renders schema-only fields and preserves tri-state defaults", async () => {
    const data = copyDraft();
    data.coordinator!.data = {
      name: "My bundle",
      executor: { config: { harness: "codex-native" } },
      prompt: "Coordinate the work",
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
    fireEvent.change(screen.getByLabelText("/interaction"), {
      target: { value: '{"mode":"chat"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(hooks.update.mutateAsync).toHaveBeenCalledOnce());
    expect(hooks.update.mutateAsync.mock.calls[0][0].request.patches).toContainEqual({
      file: "config.yaml",
      op: "add",
      path: "/interaction",
      value: { mode: "chat" },
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
          type: path === "/executor/context_window" ? "integer" : "string",
          group: "executor",
          required: false,
          secret: path === "/executor/auth",
          translation_key: path,
          editor: "generic-tree",
        })),
      },
    });

    renderPage();

    expect(screen.getByLabelText("/executor/type")).toHaveValue("provider");
    expect(screen.getByLabelText("/executor/context_window")).toHaveValue("128000");
    expect(screen.getByLabelText("/executor/config")).toHaveValue(
      '{\n  "provider_region": "us-east",\n  "retries": 2\n}',
    );
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
      expect(workerButtons.findIndex((button) => button.textContent === "worker-2")).toBeLessThan(
        workerButtons.findIndex((button) => button.textContent === "reviewer"),
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
          .map((button) => button.textContent),
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
        .map((button) => button.textContent),
    ).toEqual(["worker-2", "reviewer"]);

    fireEvent.click(screen.getByRole("button", { name: "Reload server version" }));
    await waitFor(() => expect(refetch).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("button", { name: /^(worker-2|reviewer)$/ })
          .map((button) => button.textContent),
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
