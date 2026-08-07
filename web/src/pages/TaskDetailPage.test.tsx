import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAvailableAgents } from "@/hooks/useAvailableAgents";
import { useProjectConfig, useProjects } from "@/hooks/useConversations";
import { useHosts } from "@/hooks/useHosts";
import {
  cancelWorkItemRun,
  createWorkItemRun,
  getWorkItem,
  listWorkItemRuns,
  updateWorkItem,
  type UpdateWorkItemInput,
  type WorkItem,
} from "@/lib/workItemsApi";
import type * as WorkItemsModule from "@/lib/workItemsApi";
import { TaskDetailPage } from "./TaskDetailPage";

vi.mock("@/hooks/useAvailableAgents", () => ({ useAvailableAgents: vi.fn() }));
vi.mock("@/hooks/useConversations", () => ({
  useProjects: vi.fn(),
  useProjectConfig: vi.fn(),
}));
vi.mock("@/hooks/useHosts", () => ({ useHosts: vi.fn() }));
vi.mock("@/lib/workItemsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof WorkItemsModule>()),
  getWorkItem: vi.fn(),
  listWorkItemRuns: vi.fn(),
  createWorkItemRun: vi.fn(),
  cancelWorkItemRun: vi.fn(),
  updateWorkItem: vi.fn(),
}));

const task: WorkItem = {
  id: "task_1",
  object: "work_item",
  title: "Deliver durable workflows",
  description: "Keep each execution auditable.",
  state: "backlog",
  priority: "high",
  project_id: "project_1",
  assignee_agent_id: "agent_1",
  due_at: 1_786_723_200,
  created_at: 1_786_086_000,
  updated_at: 1_786_089_600,
  completed_at: null,
  version: 3,
};

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tasks/task_1"]}>
        <Routes>
          <Route path="/tasks" element={<LocationProbe />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getWorkItem).mockReset().mockResolvedValue(task);
  vi.mocked(updateWorkItem).mockReset();
  vi.mocked(listWorkItemRuns).mockReset().mockResolvedValue([]);
  vi.mocked(createWorkItemRun).mockReset();
  vi.mocked(cancelWorkItemRun).mockReset();
  vi.mocked(useProjects).mockReturnValue({
    data: [{ id: "project_1", name: "Project Alpha" }],
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useProjects>);
  vi.mocked(useAvailableAgents).mockReturnValue({
    data: [{ id: "agent_1", name: "codex", display_name: "Codex", harness: "codex-native" }],
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useAvailableAgents>);
  vi.mocked(useProjectConfig).mockReturnValue({
    data: { host_id: "runtime_1", workspace: "/workspace" },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useProjectConfig>);
  vi.mocked(useHosts).mockReturnValue({
    data: [
      {
        host_id: "runtime_1",
        name: "Local runtime",
        owner: "local",
        status: "online",
        configured_harnesses: { "codex-native": true },
      },
    ],
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useHosts>);
});

afterEach(cleanup);

describe("TaskDetailPage", () => {
  it("shows loading while the task is unresolved", () => {
    vi.mocked(getWorkItem).mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading task detail…")).toBeInTheDocument();
  });

  it("shows the not-found state when the task request fails", async () => {
    vi.mocked(getWorkItem).mockRejectedValue(new Error("404"));
    renderPage();

    expect(
      await screen.findByText("This task does not exist or is not accessible"),
    ).toBeInTheDocument();
  });

  it("renders authoritative task fields and does not fabricate runs", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: task.title })).toBeInTheDocument();
    expect(screen.getByText(task.description as string)).toBeInTheDocument();
    expect(screen.getByText("Project Alpha")).toBeInTheDocument();
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Aug 15, 2026, 12:00 AM")).toBeInTheDocument();
    expect(screen.getByText(task.id)).toBeInTheDocument();
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /run/i })).not.toBeInTheDocument();
  });

  it("preserves the assignee id when the referenced agent was deleted", async () => {
    vi.mocked(useAvailableAgents).mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useAvailableAgents>);

    renderPage();

    expect(await screen.findByText("Deleted agent · agent_1")).toBeInTheDocument();
  });

  it("starts a real TaskRun with the project runtime defaults", async () => {
    vi.mocked(createWorkItemRun).mockResolvedValue({
      id: "run_1",
      object: "work_item_run",
      work_item_id: "task_1",
      session_id: "session_1",
      agent_id: "agent_1",
      runtime_id: "runtime_1",
      workspace: "/workspace",
      state: "running",
      trigger: "manual",
      retry_of_run_id: null,
      queued_at: 1,
      started_at: 2,
      finished_at: null,
      updated_at: 2,
      result_summary: null,
      failure: null,
      artifact_refs: [],
      usage_refs: ["session:session_1"],
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Start run" }));
    expect(screen.getByRole("combobox", { name: "Runtime" })).toHaveValue("runtime_1");
    expect(screen.getByRole("textbox", { name: "Working directory" })).toHaveValue("/workspace");
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(createWorkItemRun).toHaveBeenCalledWith("task_1", {
        runtime_id: "runtime_1",
        workspace: "/workspace",
      }),
    );
  });

  it("patches state and priority with the latest optimistic-lock version", async () => {
    vi.mocked(updateWorkItem).mockImplementation(
      async (_id: string, input: UpdateWorkItemInput) => ({
        ...task,
        ...input,
        version: input.expected_version + 1,
      }),
    );
    renderPage();

    const stateSelect = await screen.findByRole("combobox", { name: "State" });
    fireEvent.change(stateSelect, { target: { value: "in_progress" } });
    await waitFor(() =>
      expect(updateWorkItem).toHaveBeenCalledWith("task_1", {
        state: "in_progress",
        expected_version: 3,
      }),
    );

    const prioritySelect = screen.getByRole("combobox", { name: "Priority" });
    await waitFor(() => {
      expect(stateSelect).toHaveValue("in_progress");
      expect(stateSelect).not.toBeDisabled();
    });
    fireEvent.change(prioritySelect, { target: { value: "urgent" } });
    await waitFor(() =>
      expect(updateWorkItem).toHaveBeenLastCalledWith("task_1", {
        priority: "urgent",
        expected_version: 4,
      }),
    );
  });

  it("returns to the task collection", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Back to Tasks" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/tasks");
  });
});
