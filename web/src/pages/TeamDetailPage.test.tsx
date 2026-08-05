import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TeamDetailPage } from "./TeamDetailPage";

vi.mock("@/hooks/useTeams", () => ({
  useTeam: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateTeam: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
  useUpdateTeam: () => ({ mutateAsync: vi.fn(), isPending: false, isError: false }),
}));
vi.mock("@/hooks/useWorkspaces", () => ({ useWorkspaces: () => ({ data: [], isLoading: false }) }));
vi.mock("@/hooks/useFeishuInstall", () => ({
  useFeishuInstall: () => ({
    mutateAsync: vi.fn().mockResolvedValue({
      session: "s",
      status: "pending",
      verification_uri_complete: "https://example.test",
    }),
    isPending: false,
  }),
  useFeishuInstallStatus: () => ({ data: undefined }),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/teams/new"]}>
      <Routes>
        <Route path="/teams/:teamId" element={<TeamDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TeamDetailPage", () => {
  it("edits coordinator, workers, workspace and pairing", () => {
    renderPage();
    expect(screen.getByText("Team Builder")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Coordinator" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "连接飞书" }));
    expect(screen.getByText("Agent Pairing")).toBeVisible();
  });

  it("validates coordinator, ids and concurrency before saving", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Team name"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save team" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Team name is required");
  });
});
