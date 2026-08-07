import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type * as DndKitModule from "@dnd-kit/core";
import { useAvailableAgents } from "@/hooks/useAvailableAgents";
import { useProjects } from "@/hooks/useConversations";
import { createWorkItem, listWorkItems, updateWorkItem, type WorkItem } from "@/lib/workItemsApi";
import type * as WorkItemsModule from "@/lib/workItemsApi";
import { TasksPage } from "./TasksPage";

vi.mock("@/hooks/useAvailableAgents", () => ({ useAvailableAgents: vi.fn() }));
vi.mock("@/hooks/useConversations", () => ({ useProjects: vi.fn() }));
vi.mock("@dnd-kit/core", async (importOriginal) => ({
  ...(await importOriginal<typeof DndKitModule>()),
  DndContext: ({
    children,
    onDragEnd,
  }: PropsWithChildren<{
    onDragEnd?: (event: { active: { id: string }; over: { id: string } }) => void;
  }>) => (
    <div>
      <button
        type="button"
        data-testid="move-task-to-todo"
        onClick={() => onDragEnd?.({ active: { id: "task_1" }, over: { id: "todo" } })}
      />
      {children}
    </div>
  ),
  useDraggable: () => ({
    attributes: {},
    isDragging: false,
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
  }),
  useDroppable: () => ({ isOver: false, setNodeRef: vi.fn() }),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));
vi.mock("@/lib/workItemsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof WorkItemsModule>()),
  listWorkItems: vi.fn(),
  createWorkItem: vi.fn(),
  updateWorkItem: vi.fn(),
}));

const backlog: WorkItem = {
  id: "task_1",
  object: "work_item",
  title: "Ship task board",
  description: "Board and list views",
  state: "backlog",
  priority: "high",
  project_id: "project_1",
  assignee_agent_id: "agent_1",
  due_at: null,
  created_at: 1,
  updated_at: null,
  completed_at: null,
  version: 1,
};

function LocationProbe() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function renderPage(path = "/tasks") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TasksPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(listWorkItems).mockReset().mockResolvedValue([backlog]);
  vi.mocked(createWorkItem).mockReset();
  vi.mocked(updateWorkItem).mockReset();
  vi.mocked(useProjects).mockReturnValue({
    data: [{ id: "project_1", name: "Alpha" }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useProjects>);
  vi.mocked(useAvailableAgents).mockReturnValue({
    data: [{ id: "agent_1", name: "polly", display_name: "Polly" }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useAvailableAgents>);
});

afterEach(() => cleanup());

describe("TasksPage", () => {
  it("renders the real Task board and persists list view in the URL", async () => {
    renderPage();

    expect(await screen.findByText("Ship task board")).toBeInTheDocument();
    expect(screen.getByTestId("task-board")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Backlog" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByTestId("location")).toHaveTextContent("?view=list");
    expect(screen.getByRole("table", { name: "Tasks" })).toBeInTheDocument();
  });

  it("creates a task from the core-fields dialog", async () => {
    const created = {
      ...backlog,
      id: "task_2",
      title: "New durable task",
      priority: "urgent" as const,
      due_at: Math.floor(new Date("2026-08-15T00:00:00").getTime() / 1000),
    };
    vi.mocked(listWorkItems)
      .mockReset()
      .mockResolvedValueOnce([backlog])
      .mockResolvedValue([created, backlog]);
    vi.mocked(createWorkItem).mockResolvedValue(created);
    renderPage();
    await screen.findByText("Ship task board");

    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Title"), {
      target: { value: "New durable task" },
    });
    fireEvent.change(within(dialog).getByLabelText("Priority"), { target: { value: "urgent" } });
    fireEvent.input(within(dialog).getByLabelText("Due date"), {
      target: { value: "2026-08-15" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(createWorkItem).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "New durable task",
          priority: "urgent",
          due_at: created.due_at,
        }),
        expect.anything(),
      ),
    );
    expect(await screen.findByText("New durable task")).toBeInTheDocument();
  });

  it("moves a card after drag end and sends its current version", async () => {
    vi.mocked(updateWorkItem).mockResolvedValue({ ...backlog, state: "todo", version: 2 });
    renderPage();
    await screen.findByText("Ship task board");
    fireEvent.click(screen.getByTestId("move-task-to-todo"));

    await waitFor(() =>
      expect(updateWorkItem).toHaveBeenCalledWith("task_1", {
        state: "todo",
        expected_version: 1,
      }),
    );
  });
});
