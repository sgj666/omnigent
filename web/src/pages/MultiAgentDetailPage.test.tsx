import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MultiAgentDetailPage } from "./MultiAgentDetailPage";

const hooks = vi.hoisted(() => ({
  detail: vi.fn(),
  schema: vi.fn(),
  create: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
  update: { mutateAsync: vi.fn(), isPending: false, isError: false, error: null },
  connect: { mutateAsync: vi.fn(), isPending: false },
}));

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgent: () => hooks.detail(),
  useAgentFormSchema: () => hooks.schema(),
  useCreateMultiAgent: () => hooks.create,
  useUpdateMultiAgent: () => hooks.update,
  useConnectMultiAgentFeishu: () => hooks.connect,
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

const draft = {
  agent: {
    id: "ag_custom",
    name: "My bundle",
    description: "Coordinator and reviewer",
    harness: "codex-native",
    model_source: "local-default",
    worker_count: 1,
    skill_count: 0,
    mcp_count: 0,
    version: 3,
    updated_at: 1_786_000_000,
    builtin: false,
    editable: true,
    validation_status: "invalid",
    feishu_status: "pending",
    recent_run: null,
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

describe("MultiAgentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.detail.mockReturnValue({ data: draft, isLoading: false, isError: false });
    hooks.schema.mockReturnValue({ data: { schema_version: "1", fields: [] } });
  });

  it("renders the visual editor without pinning a local-default model", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "My bundle" })).toBeVisible();
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByText("Use local default")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Visual" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Advanced YAML" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
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
});
