import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useHosts } from "@/hooks/useHosts";
import { RuntimePage } from "./RuntimePage";

vi.mock("@/hooks/useHosts", () => ({ useHosts: vi.fn() }));

function renderPage(path = "/runtime") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <RuntimePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useHosts).mockReturnValue({
    data: [
      {
        host_id: "host-1",
        name: "Development Mac",
        owner: "local",
        status: "online",
        configured_harnesses: { "codex-native": true, "claude-native": "needs-auth" },
      },
      { host_id: "host-2", name: "Offline box", owner: "local", status: "offline" },
    ],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useHosts>);
});

describe("RuntimePage", () => {
  it("shows only installed runtimes and makes the machine card a detail link", async () => {
    renderPage();
    expect(await screen.findByText("Development Mac")).toBeInTheDocument();
    expect(screen.getByText("1 machine online")).toBeInTheDocument();
    expect(screen.getByText("1 available runtime")).toBeInTheDocument();
    expect(screen.getByText("1 installed runtime")).toBeInTheDocument();
    expect(screen.getByText("Codex CLI")).toBeInTheDocument();
    expect(screen.queryByText(/Needs setup/)).toBeNull();
    expect(
      screen.getByRole("link", { name: "View runtime details for Development Mac" }),
    ).toHaveAttribute("href", "/runtime/host-1");
  });

  it("uses the URL status filter", async () => {
    renderPage("/runtime?status=offline");
    expect(await screen.findByText("Offline box")).toBeInTheDocument();
    expect(screen.queryByText("Development Mac")).toBeNull();
  });

  it("shows a dedicated permission state when host access is forbidden", async () => {
    vi.mocked(useHosts).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("403 Forbidden"),
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useHosts>);

    renderPage();

    expect(await screen.findByText("You don’t have access to this collection")).toBeInTheDocument();
  });
});
