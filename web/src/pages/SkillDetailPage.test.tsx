import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  discardSkillDraft,
  dryRunSkillDraft,
  getSkill,
  getSkillDraft,
  saveSkillDraft,
  validateSkillDraft,
  type SkillDraftResponse,
} from "@/lib/skillsApi";
import { SkillDetailPage } from "./SkillDetailPage";

vi.mock("@/lib/skillsApi", () => ({
  discardSkillDraft: vi.fn(),
  dryRunSkillDraft: vi.fn(),
  getSkill: vi.fn(),
  getSkillDraft: vi.fn(),
  saveSkillDraft: vi.fn(),
  validateSkillDraft: vi.fn(),
}));

const files = [
  { path: "SKILL.md", content: "# Review helper", size: 15 },
  { path: "references/checklist.md", content: "# Checklist", size: 11 },
];
const noDraft: SkillDraftResponse = {
  draft: null,
  baseline_current: false,
  publish_enabled: false,
};
const savedDraft: SkillDraftResponse = {
  draft: {
    skill_id: "skill-1",
    baseline_sha: "a".repeat(40),
    relative_path: "skills/review-helper",
    updated_at: 123,
    files,
    validation: { status: "valid", diagnostics: [] },
  },
  baseline_current: true,
  publish_enabled: false,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/skills/skill-1"]}>
        <Routes>
          <Route path="/skills/:skillId" element={<SkillDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSkill).mockResolvedValue({
    id: "skill-1",
    object: "skill",
    name: "review-helper",
    description: "Review changes safely.",
    relative_path: "skills/review-helper",
    validation_status: "valid",
    diagnostics: [],
    file_count: 2,
    files,
    source: {
      remote_url: "https://gitlab.example.com/spec.git",
      ref: "feature",
      skills_path: "skills",
      commit_sha: "abcdef0123456789abcdef0123456789abcdef01",
      synced_at: 123,
      sync_status: "current",
      error: null,
      writable: false,
    },
  });
  vi.mocked(getSkillDraft).mockResolvedValue(noDraft);
  vi.mocked(saveSkillDraft).mockResolvedValue(savedDraft);
  vi.mocked(validateSkillDraft).mockResolvedValue({
    validation: { status: "valid", diagnostics: [] },
    baseline_current: true,
  });
  vi.mocked(discardSkillDraft).mockResolvedValue();
});

describe("SkillDetailPage", () => {
  it("renders immutable files and switches the active file", async () => {
    renderPage();
    expect(await screen.findByText("Review changes safely.")).toBeInTheDocument();
    expect(screen.getByText("# Review helper")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "references/checklist.md" }));
    expect(screen.getByText("# Checklist")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create local draft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish disabled" })).toBeDisabled();
  });

  it("creates a local draft and validates the current files", async () => {
    vi.mocked(getSkillDraft).mockResolvedValueOnce(noDraft).mockResolvedValue(savedDraft);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Create local draft" }));
    expect(await screen.findByRole("textbox", { name: "Edit SKILL.md" })).toBeInTheDocument();
    expect(saveSkillDraft).toHaveBeenCalledWith("skill-1", files);

    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(validateSkillDraft).toHaveBeenCalledWith("skill-1"));
    expect(saveSkillDraft).toHaveBeenLastCalledWith("skill-1", files);
    expect(screen.getByText("Draft validation")).toBeInTheDocument();
    expect(
      screen.getByText("Directory, metadata, references, and sensitive-information checks passed."),
    ).toBeInTheDocument();
  });

  it("saves edits before Dry Run and keeps Publish disabled", async () => {
    vi.mocked(getSkillDraft).mockResolvedValue(savedDraft);
    vi.mocked(dryRunSkillDraft).mockResolvedValue({
      remote_url: "https://gitlab.example.com/spec.git",
      ref: "feature",
      baseline_sha: "a".repeat(40),
      relative_path: "skills/review-helper",
      changed_files: ["SKILL.md"],
      diff: "+Review changes carefully.",
      validation: { status: "valid", diagnostics: [] },
      publish_enabled: false,
    });
    renderPage();

    const editor = await screen.findByRole("textbox", { name: "Edit SKILL.md" });
    fireEvent.change(editor, {
      target: { value: "# Review helper\nReview changes carefully." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Dry Run" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("https://gitlab.example.com/spec.git")).toBeInTheDocument();
    expect(within(dialog).getByText("skills/review-helper")).toBeInTheDocument();
    expect(within(dialog).getByText("a".repeat(40))).toBeInTheDocument();
    expect(within(dialog).getByText("1 changed file")).toBeInTheDocument();
    expect(within(dialog).getByText(/Review changes carefully/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Publish disabled" })).toBeDisabled();
    expect(saveSkillDraft).toHaveBeenCalledWith("skill-1", [
      {
        path: "SKILL.md",
        content: "# Review helper\nReview changes carefully.",
        size: 41,
      },
      files[1],
    ]);
    expect(saveSkillDraft).toHaveBeenCalledBefore(vi.mocked(dryRunSkillDraft));
  });

  it("discards a local draft and restores immutable files", async () => {
    vi.mocked(getSkillDraft).mockResolvedValueOnce(savedDraft).mockResolvedValue(noDraft);
    renderPage();

    expect(await screen.findByRole("textbox", { name: "Edit SKILL.md" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));

    expect(await screen.findByRole("button", { name: "Create local draft" })).toBeInTheDocument();
    expect(discardSkillDraft).toHaveBeenCalledWith("skill-1");
    expect(screen.getByText("# Review helper")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Edit SKILL.md" })).not.toBeInTheDocument();
  });

  it("warns when the draft baseline is stale", async () => {
    vi.mocked(getSkillDraft).mockResolvedValue({
      ...savedDraft,
      baseline_current: false,
    });
    renderPage();

    expect(
      await screen.findByText(
        "The repository baseline has changed. Discard this draft or recreate it from the latest version.",
      ),
    ).toHaveAttribute("role", "alert");
  });
});
