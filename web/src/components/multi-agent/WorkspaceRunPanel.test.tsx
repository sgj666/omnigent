import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiError";
import { createRun } from "@/lib/runsApi";
import { runInspectorFixture } from "@/lib/runsApi.fixture";
import { WorkspaceRunPanel } from "./WorkspaceRunPanel";

vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({
    data: [
      { id: "ws-1", root_path: "/repo-one", repositories: [] },
      { id: "ws-2", root_path: "/repo-two", repositories: [] },
    ],
    isLoading: false,
  }),
  useCreateWorkspace: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({
    data: [
      { host_id: "host-1", name: "host-one", status: "online" },
      { host_id: "host-2", name: "host-two", status: "online" },
    ],
  }),
}));
vi.mock("@/lib/runsApi", () => ({ createRun: vi.fn() }));

const startRun = vi.mocked(createRun);

function startedRun(id: string) {
  return { ...runInspectorFixture.run, object: "run" as const, id };
}

function renderPanel(agentId = "agent-1") {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <MemoryRouter>
      <WorkspaceRunPanel agentId={agentId} />
    </MemoryRouter>,
    { wrapper },
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  startRun.mockReset();
});

describe("WorkspaceRunPanel", () => {
  it("submits the complete Web Run contract and reuses its event id after a failure", async () => {
    startRun
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(startedRun("run-1"))
      .mockResolvedValueOnce(startedRun("run-2"));
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
    renderPanel();

    fireEvent.change(screen.getByLabelText("Task input"), {
      target: { value: "Investigate checkout" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(2));
    expect(startRun).toHaveBeenNthCalledWith(1, {
      agent_id: "agent-1",
      workspace_id: "ws-1",
      input: "Investigate checkout",
      source: "web",
      source_event_id: "web:00000000-0000-4000-8000-000000000001",
      host_id: "host-1",
      execution_mode: "auto",
    });
    expect(startRun.mock.calls[1]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000001",
    );

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(3));
    expect(startRun.mock.calls[2]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000002",
    );
  });

  it("uses a new event id after an explicit server rejection", async () => {
    startRun
      .mockRejectedValueOnce(new ApiError("invalid request", { status: 422 }))
      .mockResolvedValueOnce(startedRun("run-1"));
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000011")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000012");
    renderPanel();

    fireEvent.change(screen.getByLabelText("Task input"), {
      target: { value: "Investigate checkout" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(2));
    expect(startRun.mock.calls[0]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000011",
    );
    expect(startRun.mock.calls[1]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000012",
    );
  });

  it("reuses its event id after an ambiguous server failure", async () => {
    startRun
      .mockRejectedValueOnce(new ApiError("bad gateway", { status: 502 }))
      .mockResolvedValueOnce(startedRun("run-1"));
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000031")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000032");
    renderPanel();

    fireEvent.change(screen.getByLabelText("Task input"), {
      target: { value: "Investigate checkout" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(2));
    expect(startRun.mock.calls[0]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000031",
    );
    expect(startRun.mock.calls[1]?.[0].source_event_id).toBe(
      "web:00000000-0000-4000-8000-000000000031",
    );
  });

  it("uses a new event id whenever agent, input, workspace, or host changes", async () => {
    startRun
      .mockRejectedValueOnce(new Error("offline-1"))
      .mockRejectedValueOnce(new Error("offline-2"))
      .mockRejectedValueOnce(new Error("offline-3"))
      .mockRejectedValueOnce(new Error("offline-4"))
      .mockResolvedValueOnce(startedRun("run-1"));
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000021")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000022")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000023")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000024")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000025");
    const view = renderPanel();

    const input = screen.getByLabelText("Task input");
    fireEvent.change(input, { target: { value: "First input" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(1));

    fireEvent.change(input, { target: { value: "Second input" } });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: /\/repo-two/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(3));

    const host = screen.getByRole("combobox");
    host.focus();
    fireEvent.keyDown(host, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "host-two · online" }));
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(4));

    view.rerender(
      <MemoryRouter>
        <WorkspaceRunPanel agentId="agent-2" />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(startRun).toHaveBeenCalledTimes(5));

    expect(startRun.mock.calls.map((call) => call[0].source_event_id)).toEqual([
      "web:00000000-0000-4000-8000-000000000021",
      "web:00000000-0000-4000-8000-000000000022",
      "web:00000000-0000-4000-8000-000000000023",
      "web:00000000-0000-4000-8000-000000000024",
      "web:00000000-0000-4000-8000-000000000025",
    ]);
    expect(startRun.mock.calls[2]?.[0].workspace_id).toBe("ws-2");
    expect(startRun.mock.calls[3]?.[0].host_id).toBe("host-2");
    expect(startRun.mock.calls[4]?.[0].agent_id).toBe("agent-2");
  });
});
