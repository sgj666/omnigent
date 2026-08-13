import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSkillsRepositoryConfig,
  listSkills,
  syncSkills,
  updateSkillsRepositoryConfig,
} from "@/lib/skillsApi";
import { SkillsPage } from "./SkillsPage";

vi.mock("@/lib/skillsApi", () => ({
  getSkillsRepositoryConfig: vi.fn(),
  listSkills: vi.fn(),
  syncSkills: vi.fn(),
  updateSkillsRepositoryConfig: vi.fn(),
}));

const inventory = {
  object: "list" as const,
  source: {
    remote_url: "https://gitlab.example.com/spec.git",
    ref: "feature",
    skills_path: "skills",
    commit_sha: "abcdef0123456789abcdef0123456789abcdef01",
    synced_at: 123,
    sync_status: "current" as const,
    error: null,
    writable: false as const,
  },
  data: [
    {
      id: "skill-1",
      object: "skill" as const,
      name: "review-helper",
      description: "Review changes safely.",
      relative_path: "skills/review-helper",
      validation_status: "valid" as const,
      diagnostics: [],
      file_count: 2,
    },
    {
      id: "skill-2",
      object: "skill" as const,
      name: "broken-helper",
      description: "",
      relative_path: "skills/broken-helper",
      validation_status: "error" as const,
      diagnostics: ["Missing frontmatter field: description"],
      file_count: 1,
    },
  ],
};

const repositoryConfig = {
  object: "skill_repository_config" as const,
  url: "https://gitlab.example.com/spec.git",
  ref: "feature",
  path: "skills",
  username: "oauth2",
  token_configured: true,
  editable: true,
  source: "database" as const,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SkillsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(listSkills).mockResolvedValue(inventory);
  vi.mocked(syncSkills).mockResolvedValue(inventory);
  vi.mocked(getSkillsRepositoryConfig).mockResolvedValue(repositoryConfig);
  vi.mocked(updateSkillsRepositoryConfig).mockResolvedValue({
    config: repositoryConfig,
    inventory,
  });
});

describe("SkillsPage", () => {
  it("shows traceable repository facts and validation state", async () => {
    renderPage();
    expect(await screen.findByText("review-helper")).toBeInTheDocument();
    expect(screen.getByText("broken-helper")).toBeInTheDocument();
    expect(screen.getAllByText("abcdef012345")).toHaveLength(3);
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.getAllByText("Needs attention").length).toBeGreaterThan(0);
  });

  it("filters by validation state and performs an explicit read-only sync", async () => {
    renderPage();
    await screen.findByText("review-helper");
    fireEvent.click(screen.getByRole("button", { name: "Needs attention, 1" }));
    expect(screen.queryByText("review-helper")).not.toBeInTheDocument();
    expect(screen.getByText("broken-helper")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Sync repository" }));
    await waitFor(() => expect(syncSkills).toHaveBeenCalledTimes(1));
  });

  it("edits the shared repository config without ever pre-filling the token", async () => {
    renderPage();
    await screen.findByText("review-helper");

    fireEvent.click(await screen.findByRole("button", { name: "Edit repository" }));
    expect(screen.getByLabelText("Repository URL")).toHaveValue(
      "https://gitlab.example.com/spec.git",
    );
    expect(screen.getByLabelText("Access token")).toHaveValue("");
    expect(
      screen.getByText("A token is configured. Leave blank to keep it unchanged."),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Ref"), { target: { value: "release" } });
    fireEvent.click(screen.getByRole("button", { name: "Save repository" }));

    await waitFor(() =>
      expect(updateSkillsRepositoryConfig).toHaveBeenCalledWith(
        {
          url: "https://gitlab.example.com/spec.git",
          ref: "release",
          path: "skills",
          username: "oauth2",
        },
        expect.anything(),
      ),
    );
  });

  it("does not show repository editing to non-admin viewers", async () => {
    vi.mocked(getSkillsRepositoryConfig).mockResolvedValue({
      ...repositoryConfig,
      editable: false,
    });
    renderPage();
    await screen.findByText("review-helper");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Edit repository" })).not.toBeInTheDocument(),
    );
  });
});
