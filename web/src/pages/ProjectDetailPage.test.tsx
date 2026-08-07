import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useProjectSessions } from "@/hooks/useConversations";
import { getProject, listProjectArtifacts } from "@/lib/projectsApi";
import { ProjectDetailPage } from "./ProjectDetailPage";

vi.mock("@/hooks/useConversations", () => ({ useProjectSessions: vi.fn() }));
vi.mock("@/lib/projectsApi", () => ({
  getProject: vi.fn(),
  listProjectArtifacts: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/p1"]}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getProject).mockResolvedValue({
    id: "p1",
    name: "Alpha",
    session_count: 1,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_100,
    config: {
      agent_id: "polly",
      host_id: "host-1",
      workspace: "/work/alpha",
      use_worktree: true,
    },
  });
  vi.mocked(listProjectArtifacts).mockResolvedValue([
    {
      id: "file-1",
      object: "project.artifact",
      project_id: "p1",
      name: "release-notes.md",
      content_type: "text/markdown",
      bytes: 2048,
      created_at: 1_700_000_300,
      version: 2,
      visibility: "private",
      available: true,
      summary: "Prepared the final release notes.",
      work_item_id: "task-1",
      work_item_title: "Publish release notes",
      work_item_run_id: "run-123456789",
      session_id: "s1",
      download_url: "/v1/sessions/s1/resources/files/file-1/content",
    },
  ]);
  vi.mocked(useProjectSessions).mockReturnValue({
    data: {
      pages: [
        {
          data: [
            {
              id: "s1",
              object: "conversation",
              title: "Ship Alpha",
              created_at: 1_700_000_000,
              updated_at: 1_700_000_200,
              labels: {},
              permission_level: null,
              agent_name: "polly",
              workspace: "/work/alpha",
              status: "running",
            },
          ],
        },
      ],
    },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  } as unknown as ReturnType<typeof useProjectSessions>);
});

describe("ProjectDetailPage", () => {
  it("shows authoritative project defaults and member sessions", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByText("Ship Alpha")).toBeInTheDocument();
    expect(screen.getAllByText("polly")).toHaveLength(2);
    expect(screen.getAllByText("/work/alpha")).toHaveLength(2);
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(useProjectSessions).toHaveBeenCalledWith("Alpha", true);
  });

  it("starts a session with the project deep link", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("link", { name: "New session" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/?project=Alpha");
  });

  it("shows versioned TaskRun artifacts with Task and Session back-links", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Project artifacts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "release-notes.md" })).toHaveAttribute(
      "href",
      "/v1/sessions/s1/resources/files/file-1/content",
    );
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    expect(screen.getByText("Prepared the final release notes.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Publish release notes" })).toHaveAttribute(
      "href",
      "/tasks/task-1#run-run-123456789",
    );
    expect(screen.getByRole("link", { name: "Session" })).toHaveAttribute("href", "/c/s1");
  });
});
