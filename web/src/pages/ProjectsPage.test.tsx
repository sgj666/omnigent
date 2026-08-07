import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useProjects } from "@/hooks/useConversations";
import { listProjects } from "@/lib/projectsApi";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("@/hooks/useConversations", () => ({ useProjects: vi.fn() }));
vi.mock("@/lib/projectsApi", () => ({ listProjects: vi.fn() }));

function renderPage(path = "/projects") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ProjectsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useProjects).mockReturnValue({
    data: [
      { id: "p1", name: "Alpha" },
      { id: "p2", name: "Empty" },
      { id: null, name: "Legacy" },
    ],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useProjects>);
  vi.mocked(listProjects).mockResolvedValue([
    {
      id: "p1",
      name: "Alpha",
      session_count: 2,
      artifact_count: 1,
      latest_artifact_name: "report.md",
      created_at: 100,
      config: { agent_id: "polly" },
    },
    {
      id: "p2",
      name: "Empty",
      session_count: 0,
      artifact_count: 0,
      latest_artifact_name: null,
      created_at: 200,
      config: {},
    },
  ]);
});

describe("ProjectsPage", () => {
  it("merges first-class and legacy folders without inventing legacy counts", async () => {
    renderPage();
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("2 sessions")).toBeInTheDocument();
    expect(screen.getByText("Agent: polly")).toBeInTheDocument();
    expect(screen.getByText("1 artifact · report.md")).toBeInTheDocument();
    expect(screen.getByText("No artifacts")).toBeInTheDocument();
    expect(screen.getByText("Legacy folder")).toBeInTheDocument();
  });

  it("filters through URL-backed status and search controls", async () => {
    renderPage("/projects?status=empty");
    expect(await screen.findByText("Empty")).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "missing" },
    });
    await waitFor(() =>
      expect(screen.getByText("No projects match these filters")).toBeInTheDocument(),
    );
  });

  it("restores the selected sort from the URL and reorders the table", async () => {
    renderPage("/projects?sort=name");

    expect(await screen.findByRole("combobox", { name: "Sort projects" })).toHaveValue("name");
    await screen.findByText("Alpha");
    let rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Alpha");
    expect(rows[1]).toHaveTextContent("Empty");

    fireEvent.change(screen.getByRole("combobox", { name: "Sort projects" }), {
      target: { value: "activity" },
    });
    await waitFor(() => {
      rows = screen.getAllByRole("row").slice(1);
      expect(rows[0]).toHaveTextContent("Empty");
      expect(rows[1]).toHaveTextContent("Alpha");
    });
  });

  it("distinguishes permission denial from a generic load error", async () => {
    vi.mocked(listProjects).mockRejectedValue(new Error("403 Forbidden"));

    renderPage();

    expect(await screen.findByText("You don’t have access to this collection")).toBeInTheDocument();
    expect(
      screen.getByText("Ask an administrator for access, then try again."),
    ).toBeInTheDocument();
  });
});
