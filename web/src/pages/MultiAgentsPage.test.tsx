import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MultiAgentsPage } from "./MultiAgentsPage";

const hooks = vi.hoisted(() => ({
  clone: { mutateAsync: vi.fn(), isPending: false },
  remove: { mutateAsync: vi.fn(), isPending: false },
  import: { mutateAsync: vi.fn(), isPending: false },
  list: vi.fn(),
  feishuConnection: vi.fn(),
}));

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgents: () => hooks.list(),
  useCloneMultiAgent: () => hooks.clone,
  useDeleteMultiAgent: () => hooks.remove,
  useImportMultiAgent: () => hooks.import,
}));

vi.mock("@/hooks/useFeishuInstall", () => ({
  useAgentFeishuConnection: (agentId: string) => hooks.feishuConnection(agentId),
}));

vi.mock("@/components/multi-agent/AgentFeishuPairingDialog", () => ({
  AgentFeishuPairingDialog: () => null,
}));

const polly = {
  id: "ag_polly",
  name: "Polly",
  description: "Coding orchestrator",
  harness: "claude-sdk",
  worker_count: 7,
  skill_count: 2,
  mcp_count: 1,
  version: 4,
  readonly: true,
  digest: "sha256:0123456789abcdef",
  updated_at: 1_786_000_000,
  builtin: true,
  editable: false,
  validation_status: "valid",
};

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <MultiAgentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MultiAgentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.list.mockReturnValue({ data: [polly], isLoading: false, isError: false });
    hooks.feishuConnection.mockReturnValue({ data: null, isLoading: false, error: null });
  });

  it("renders bundle metadata and the read-only Polly template action", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Multi-Agent" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Polly" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Polly" })).toHaveAttribute(
      "href",
      "/multi-agents/ag_polly",
    );
    expect(screen.getByText("Built-in · Read only")).toBeVisible();
    expect(screen.getByText("7 workers")).toBeVisible();
    expect(screen.getByText("Version 4")).toBeVisible();
    expect(screen.getByText("0123456789ab")).toBeVisible();
    expect(screen.getByRole("button", { name: "Use this template" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Feishu" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "href",
      "/multi-agents/new",
    );
    expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
  });

  it("clones a template with an AgentSpec-safe name", async () => {
    hooks.clone.mutateAsync.mockResolvedValue({ card: { id: "ag_copy" } });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Use this template" }));

    await waitFor(() =>
      expect(hooks.clone.mutateAsync).toHaveBeenCalledWith({
        agent_id: "ag_polly",
        input: { name: "Polly-copy" },
      }),
    );
  });

  it("shows an explicit empty state", () => {
    hooks.list.mockReturnValue({ data: [], isLoading: false, isError: false });
    renderPage();

    expect(screen.getByText("No Multi-Agent bundles yet")).toBeVisible();
  });

  it("shows a dedicated permission state when the catalog is forbidden", () => {
    hooks.list.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: Object.assign(new Error("Forbidden"), { status: 403 }),
    });

    renderPage();

    expect(screen.getByText("You don’t have access to this collection")).toBeVisible();
  });

  it("shows the connected Feishu identity and a clear rebinding action", () => {
    hooks.feishuConnection.mockReturnValue({
      data: { status: "connected", bot_name: "Omnigent Assistant" },
      isLoading: false,
      error: null,
    });

    renderPage();

    expect(screen.getByText("Connected to Feishu")).toBeVisible();
    expect(screen.getByText("Omnigent Assistant")).toBeVisible();
    expect(screen.getByRole("button", { name: "Change Feishu binding" })).toBeVisible();
  });

  it("hides zero-worker built-ins without hiding user bundles", () => {
    hooks.list.mockReturnValue({
      data: [
        { ...polly, id: "ag_wrapper", name: "antigravity-native-ui", worker_count: 0 },
        {
          ...polly,
          id: "ag_empty",
          name: "My future setup",
          worker_count: 0,
          builtin: false,
          readonly: false,
          editable: true,
        },
        polly,
      ],
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(screen.queryByRole("heading", { name: "antigravity-native-ui" })).toBeNull();
    expect(screen.getByRole("heading", { name: "My future setup" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Polly" })).toBeVisible();
  });

  it("shows the empty state when only internal wrappers were returned", () => {
    hooks.list.mockReturnValue({
      data: [{ ...polly, id: "ag_wrapper", name: "kiro-native-ui", worker_count: 0 }],
      isLoading: false,
      isError: false,
    });

    renderPage();

    expect(screen.getByText("No Multi-Agent bundles yet")).toBeVisible();
  });
});
