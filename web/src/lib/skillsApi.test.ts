import { beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import {
  discardSkillDraft,
  dryRunSkillDraft,
  getSkill,
  getSkillDraft,
  listSkills,
  saveSkillDraft,
  syncSkills,
  validateSkillDraft,
} from "./skillsApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

const response = {
  object: "list" as const,
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
  ],
  source: {
    remote_url: "https://gitlab.example.com/spec.git",
    ref: "feature",
    skills_path: "skills",
    commit_sha: "a".repeat(40),
    synced_at: 123,
    sync_status: "current" as const,
    error: null,
    writable: false,
  },
};

beforeEach(() => vi.mocked(authenticatedFetch).mockReset());

describe("skillsApi", () => {
  it("lists and explicitly syncs the read-only inventory", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify(response)));
    await expect(listSkills()).resolves.toEqual(response);
    expect(authenticatedFetch).toHaveBeenNthCalledWith(1, "/v1/skills", { signal: undefined });

    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify(response)));
    await expect(syncSkills()).resolves.toEqual(response);
    expect(authenticatedFetch).toHaveBeenNthCalledWith(2, "/v1/skills/sync", { method: "POST" });
  });

  it("loads one skill with immutable file contents", async () => {
    const detail = {
      ...response.data[0],
      source: response.source,
      files: [{ path: "SKILL.md", content: "# Review", size: 8 }],
    };
    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify(detail)));

    await expect(getSkill("skill/1")).resolves.toEqual(detail);
    expect(authenticatedFetch).toHaveBeenCalledWith("/v1/skills/skill%2F1", {
      signal: undefined,
    });
  });

  it("manages a local draft and never calls a publish endpoint", async () => {
    const files = [{ path: "SKILL.md", content: "# Review", size: 8 }];
    const draftResponse = {
      draft: {
        skill_id: "skill-1",
        baseline_sha: "a".repeat(40),
        relative_path: "skills/review-helper",
        updated_at: 123,
        files,
        validation: { status: "valid" as const, diagnostics: [] },
      },
      baseline_current: true,
      publish_enabled: false as const,
    };
    vi.mocked(authenticatedFetch).mockResolvedValueOnce(
      new Response(JSON.stringify(draftResponse)),
    );
    await expect(getSkillDraft("skill-1")).resolves.toEqual(draftResponse);

    vi.mocked(authenticatedFetch).mockResolvedValueOnce(
      new Response(JSON.stringify(draftResponse)),
    );
    await expect(saveSkillDraft("skill-1", files)).resolves.toEqual(draftResponse);
    expect(authenticatedFetch).toHaveBeenLastCalledWith("/v1/skills/skill-1/draft", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files }),
    });

    const validation = {
      validation: { status: "valid" as const, diagnostics: [] },
      baseline_current: true,
    };
    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify(validation)));
    await expect(validateSkillDraft("skill-1")).resolves.toEqual(validation);

    const dryRun = {
      remote_url: "https://gitlab.example.com/spec.git",
      ref: "feature",
      baseline_sha: "a".repeat(40),
      relative_path: "skills/review-helper",
      changed_files: ["SKILL.md"],
      diff: "+safe change",
      validation: validation.validation,
      publish_enabled: false as const,
    };
    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify(dryRun)));
    await expect(dryRunSkillDraft("skill-1")).resolves.toEqual(dryRun);

    vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(discardSkillDraft("skill-1")).resolves.toBeUndefined();
    expect(
      vi
        .mocked(authenticatedFetch)
        .mock.calls.some(([url]) =>
          (url instanceof Request ? url.url : String(url)).includes("publish"),
        ),
    ).toBe(false);
  });
});
