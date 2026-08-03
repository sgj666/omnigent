import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { RunInspectorPage } from "./RunInspectorPage";

vi.mock("@/hooks/useTeamRuns", () => ({
  useTeamRun: () => ({
    isLoading: false,
    isError: false,
    data: {
      id: "run-1",
      team_id: "team-1",
      workspace_id: "workspace-1",
      workspace_name: "luxury-resale-settlement",
      source: "feishu",
      status: "failed",
      tasks: [{ id: "task-1", title: "Run tests", status: "failed", depends_on: [] }],
      attempts: [{
        id: "attempt-1",
        task_id: "task-1",
        agent_profile: "test-worker",
        worktree_path: "/tmp/worktree",
        stage: "test",
        started_at: "2026-08-03T10:00:00Z",
        finished_at: "2026-08-03T10:01:00Z",
        tool_calls: 2,
        stdout: "running tests",
        stderr: "command failed",
        failure_code: "TEST_COMMAND_EXIT_1",
        retry_suggestion: "retry after fixing the test",
      }],
      parent_inbox: [{ id: "event-1", type: "worker_completed", payload: { task_id: "task-1" } }],
      evaluation: {
        completion_rate: 0,
        first_success_rate: 0,
        retry_count: 1,
        human_approval_count: 0,
        average_stage_duration: 60_000,
        parallel_utilization: 0,
        tokens: 123,
        delivery_status: "blocked",
      },
    },
  }),
}));

describe("RunInspectorPage", () => {
  it("shows the immutable workspace, task trace, failure and parent inbox", () => {
    render(<MemoryRouter initialEntries={["/runs/run-1"]}><Routes><Route path="/runs/:runId" element={<RunInspectorPage />} /></Routes></MemoryRouter>);
    expect(screen.getByText("workspace: luxury-resale-settlement")).toBeVisible();
    expect(screen.getByText("Task DAG")).toBeVisible();
    expect(screen.getByText("failure_code: TEST_COMMAND_EXIT_1")).toBeVisible();
    expect(screen.getByText("Coordinator Parent Inbox")).toBeVisible();
    expect(screen.getByText("running tests")).toBeVisible();
  });
});
