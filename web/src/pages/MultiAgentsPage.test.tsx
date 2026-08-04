import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MultiAgentsPage } from "./MultiAgentsPage";

const hooks = vi.hoisted(() => ({
  clone: { mutateAsync: vi.fn(), isPending: false },
  remove: { mutateAsync: vi.fn(), isPending: false },
  import: { mutateAsync: vi.fn(), isPending: false },
  list: vi.fn(),
}));

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgents: () => hooks.list(),
  useCloneMultiAgent: () => hooks.clone,
  useDeleteMultiAgent: () => hooks.remove,
  useImportMultiAgent: () => hooks.import,
}));

const polly = {
  id: "ag_polly",
  name: "Polly",
  description: "Coding orchestrator",
  harness: "claude-sdk",
  model_source: "local-default",
  worker_count: 7,
  skill_count: 2,
  mcp_count: 1,
  version: 4,
  digest: "sha256:0123456789abcdef",
  updated_at: 1_786_000_000,
  builtin: true,
  editable: false,
  validation_status: "valid",
  feishu_status: "disconnected",
  recent_run: null,
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
  });

  it("renders bundle metadata and the read-only Polly template action", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Multi-Agent" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Polly" })).toBeVisible();
    expect(screen.getByText("Built-in · Read only")).toBeVisible();
    expect(screen.getByText("7 workers")).toBeVisible();
    expect(screen.getByText("Version 4")).toBeVisible();
    expect(screen.getByText("0123456789ab")).toBeVisible();
    expect(screen.getByRole("button", { name: "Use this template" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "href",
      "/multi-agents/new",
    );
    expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
  });

  it("shows an explicit empty state", () => {
    hooks.list.mockReturnValue({ data: [], isLoading: false, isError: false });
    renderPage();

    expect(screen.getByText("No Multi-Agent bundles yet")).toBeVisible();
  });
});
