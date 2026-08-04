import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "@/App";
import type * as MultiAgentDetailPageModule from "@/pages/MultiAgentDetailPage";
import type * as MultiAgentsPageModule from "@/pages/MultiAgentsPage";
import { basenamedRouting, RoutingProvider } from "@/lib/routing";

const ROUTER_FUTURE_FLAGS = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
} as const;

const multiAgentModuleLoads = vi.hoisted(() => ({
  catalog: vi.fn(),
  detail: vi.fn(),
}));

vi.mock("@/pages/MultiAgentsPage", async () => {
  multiAgentModuleLoads.catalog();
  return vi.importActual<typeof MultiAgentsPageModule>("@/pages/MultiAgentsPage");
});

vi.mock("@/pages/MultiAgentDetailPage", async () => {
  multiAgentModuleLoads.detail();
  return vi.importActual<typeof MultiAgentDetailPageModule>("@/pages/MultiAgentDetailPage");
});

vi.mock("@/hooks/useMultiAgents", () => ({
  useMultiAgents: () => ({ data: [], isLoading: false, isError: false }),
  useMultiAgent: (_id: string | null) => ({
    data: {
      card: {
        id: "ag_custom",
        name: "Route bundle",
        description: null,
        harness: null,
        worker_count: 0,
        skill_count: 0,
        mcp_count: 0,
        version: 1,
        digest: "sha256:route",
        updated_at: 1_786_000_000,
        readonly: false,
        builtin: false,
        editable: true,
        validation_status: "valid",
      },
      version: 1,
      digest: "sha256:route",
      files: [],
      coordinator: {
        path: "config.yaml",
        content: "name: Route bundle\n",
        data: { name: "Route bundle" },
      },
      workers: [],
      diagnostics: [],
      schema_version: "1",
    },
    isLoading: false,
    isError: false,
  }),
  useAgentFormSchema: () => ({ data: { schema_version: "1", fields: [] } }),
  useAgentBundleOptions: () => ({ data: { harnesses: [] } }),
  useCreateMultiAgent: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useUpdateMultiAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCloneMultiAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteMultiAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useImportMultiAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/CapabilitiesContext", () => ({
  useServerInfo: () => ({ accounts_enabled: false, needs_setup: false }),
}));

vi.mock("@/shell/AppShell", async () => {
  const { Outlet } = await import("react-router-dom");
  return { AppShell: () => <Outlet /> };
});

vi.mock("@/pages/ChatPage", () => ({ ChatPage: () => <h1>Chat</h1> }));
vi.mock("@/pages/NotFoundPage", () => ({ NotFoundPage: () => <h1>Not found</h1> }));
vi.mock("@/pages/RunInspectorPage", () => ({
  RunInspectorPage: () => <h1>Run inspector</h1>,
}));
function renderRoute(path: string, basename?: string) {
  const app = <App basename={basename} />;
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE_FLAGS}>
        {basename ? (
          <RoutingProvider value={basenamedRouting(basename)}>{app}</RoutingProvider>
        ) : (
          app
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Multi-Agent routes", () => {
  it("loads catalog and detail pages lazily in a deterministic order", async () => {
    expect(multiAgentModuleLoads.catalog).not.toHaveBeenCalled();
    expect(multiAgentModuleLoads.detail).not.toHaveBeenCalled();

    const catalog = renderRoute("/multi-agents");

    expect(await screen.findByRole("heading", { name: "Multi-Agent" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "href",
      "/multi-agents/new",
    );
    expect(multiAgentModuleLoads.catalog).toHaveBeenCalledOnce();
    expect(multiAgentModuleLoads.detail).not.toHaveBeenCalled();
    catalog.unmount();

    const creation = renderRoute("/multi-agents/new");

    expect(await screen.findByRole("heading", { name: "New Multi-Agent" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to Multi-Agent" })).toHaveAttribute(
      "href",
      "/multi-agents",
    );
    expect(multiAgentModuleLoads.detail).toHaveBeenCalledOnce();
    creation.unmount();

    const detail = renderRoute("/multi-agents/ag_custom");

    expect(await screen.findByRole("heading", { name: "Route bundle" })).toBeVisible();
    expect(screen.getByText("v1 · sha256:route")).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to Multi-Agent" })).toHaveAttribute(
      "href",
      "/multi-agents",
    );
    expect(multiAgentModuleLoads.detail).toHaveBeenCalledOnce();
    detail.unmount();

    renderRoute("/ml/omnigent-embed/multi-agents", "/ml/omnigent-embed");

    expect(await screen.findByRole("heading", { name: "Multi-Agent" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute(
      "href",
      "/ml/omnigent-embed/multi-agents/new",
    );
    expect(multiAgentModuleLoads.catalog).toHaveBeenCalledOnce();
  });

  it.each([
    ["/teams", undefined],
    ["/teams/new", undefined],
    ["/teams/team-1", undefined],
    ["/ml/omnigent-embed/teams/team-1", "/ml/omnigent-embed"],
  ])("redirects legacy %s to Multi-Agent", async (path, basename) => {
    renderRoute(path, basename);

    expect(await screen.findByRole("heading", { name: "Multi-Agent" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Not found" })).toBeNull();
  });

  it("preserves the run inspector route", () => {
    renderRoute("/runs/run-1");

    expect(screen.getByRole("heading", { name: "Run inspector" })).toBeVisible();
  });
});
