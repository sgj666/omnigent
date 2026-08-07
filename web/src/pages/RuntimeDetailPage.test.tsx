import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAvailableAgents } from "@/hooks/useAvailableAgents";
import { getHost } from "@/hooks/useHosts";
import { RuntimeDetailPage } from "./RuntimeDetailPage";

vi.mock("@/hooks/useHosts", () => ({ getHost: vi.fn() }));
vi.mock("@/hooks/useAvailableAgents", () => ({ useAvailableAgents: vi.fn() }));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/runtime/host-1"]}>
        <Routes>
          <Route path="/runtime/:hostId" element={<RuntimeDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getHost).mockResolvedValue({
    host_id: "host-1",
    name: "Development Mac",
    owner: "local",
    status: "online",
    configured_harnesses: {
      "claude-native": true,
      "codex-native": "version-too-low",
      "cursor-native": "binary-missing",
    },
  });
  vi.mocked(useAvailableAgents).mockReturnValue({
    data: [
      {
        id: "agent-1",
        name: "claude-native-ui",
        display_name: "Claude Code",
        description: null,
        harness: "claude-native",
        skills: [],
      },
    ],
  } as unknown as ReturnType<typeof useAvailableAgents>);
});

describe("RuntimeDetailPage", () => {
  it("shows only installed runtimes with their linked agents", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Development Mac" })).toBeInTheDocument();
    expect(screen.getByText("This machine has 1 runtime ready to use.")).toBeInTheDocument();
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("1 agent")).toBeInTheDocument();
    expect(screen.queryByText("version-too-low")).toBeNull();
    expect(screen.queryByText("binary-missing")).toBeNull();
    expect(screen.queryByText("codex-native")).toBeNull();
    expect(screen.queryByText("cursor-native")).toBeNull();
    expect(screen.getByText("host-1")).toBeInTheDocument();
  });
});
