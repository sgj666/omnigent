import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { startMultiAgentRun } from "@/lib/multiAgentApi";
import { WorkspaceRunPanel } from "./WorkspaceRunPanel";

vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({
    data: [{ id: "ws-1", root_path: "/repo", repositories: [] }],
    isLoading: false,
  }),
  useCreateWorkspace: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({ data: [{ host_id: "host-1", status: "online" }] }),
}));
vi.mock("@/lib/multiAgentApi", () => ({ startMultiAgentRun: vi.fn() }));

const startRun = vi.mocked(startMultiAgentRun);

describe("WorkspaceRunPanel", () => {
  it("submits the complete Web Run contract and reuses its event id after a failure", async () => {
    startRun
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        id: "run-1",
        status: "queued",
        agent_id: "agent-1",
        workspace_id: "ws-1",
      })
      .mockResolvedValueOnce({
        id: "run-2",
        status: "queued",
        agent_id: "agent-1",
        workspace_id: "ws-1",
      });
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <WorkspaceRunPanel agentId="agent-1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );

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
});
