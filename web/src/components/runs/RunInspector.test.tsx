import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { runEvaluationFixture, runInspectorFixture } from "@/lib/runsApi.fixture";
import { parseRunEvaluationResponse, parseRunInspectorResponse } from "@/lib/runsApi";
import { RunInspector } from "./RunInspector";

describe("RunInspector", () => {
  it("renders the bounded Core graph and separate evaluation without raw transcript fields", () => {
    render(
      <MemoryRouter>
        <RunInspector
          inspector={parseRunInspectorResponse(runInspectorFixture)}
          evaluation={parseRunEvaluationResponse(runEvaluationFixture)}
          onRefreshEvaluation={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("run-1")).toBeVisible();
    expect(screen.getByText("agent-polly")).toBeVisible();
    expect(screen.getByText("sha256:abcdef0123456789")).toBeVisible();
    expect(screen.getByText("/work/checkout")).toBeVisible();
    expect(screen.getByText("api")).toBeVisible();
    expect(screen.getByRole("link", { name: "session-root" })).toHaveAttribute(
      "href",
      "/c/session-root",
    );
    expect(screen.getByText(/depends on task-1/i)).toBeVisible();
    expect(screen.getByText("tester")).toBeVisible();
    expect(screen.getByText("claude-sdk")).toBeVisible();
    expect(screen.getByText("claude-sonnet")).toBeVisible();
    expect(screen.getByText("/tmp/worktrees/checkout")).toBeVisible();
    expect(screen.getByText("run/checkout")).toBeVisible();
    expect(screen.getByText("commit456")).toBeVisible();
    expect(screen.getByText("The focused test command exited with status 1")).toBeVisible();
    const event = screen.getByText("parent_inbox.worker_completed").closest("article");
    expect(event).not.toBeNull();
    const eventView = within(event as HTMLElement);
    expect(eventView.getByText("session")).toBeVisible();
    expect(eventView.getByText("task-1")).toBeVisible();
    expect(eventView.getByText("attempt-1")).toBeVisible();
    expect(eventView.getByText("session-child-1")).toBeVisible();
    expect(eventView.queryByText(/RAW_STDOUT_SECRET/)).toBeNull();
    expect(eventView.queryByText(/RAW_STDERR_SECRET/)).toBeNull();
    expect(eventView.queryByText(/OPAQUE_SENSITIVE_SECRET/)).toBeNull();
    expect(eventView.getByText("completed")).toBeVisible();
    expect(eventView.getByText(new Date(1_786_000_081_000).toLocaleString())).toBeVisible();
    expect(screen.getByRole("link", { name: /session-child-2.*log/i })).toHaveAttribute(
      "href",
      "/v1/sessions/session-child-2/logs",
    );
    expect(screen.getByRole("link", { name: "test-report.xml" })).toHaveAttribute(
      "href",
      "/v1/artifacts/artifact-1",
    );
    expect(screen.getByText("unsafe-report.html")).toBeVisible();
    expect(screen.queryByRole("link", { name: "unsafe-report.html" })).toBeNull();
    expect(screen.getByText("50%")).toBeVisible();
    expect(screen.getByText("2", { selector: "dd" })).toBeVisible();
    expect(screen.queryByText(/stdout|stderr|raw transcript/i)).toBeNull();
  });

  it("counts three-way overlap by concurrent time union and never beyond attempt duration", () => {
    const inspector = parseRunInspectorResponse(runInspectorFixture);
    const attempts = [
      inspector.attempts[0],
      { ...inspector.attempts[1], started_at: 1_786_000_020, completed_at: 1_786_000_080 },
      {
        ...inspector.attempts[0],
        id: "attempt-3",
        task_id: "task-2",
        worker_name: "reviewer",
      },
    ];

    render(
      <MemoryRouter>
        <RunInspector inspector={{ ...inspector, attempts }} />
      </MemoryRouter>,
    );

    for (const attemptId of ["attempt-1", "attempt-2", "attempt-3"]) {
      const attempt = screen.getByRole("heading", { name: attemptId }).closest("article");
      expect(attempt).not.toBeNull();
      expect(within(attempt as HTMLElement).getAllByText("60 s")).toHaveLength(2);
      expect(within(attempt as HTMLElement).queryByText("120 s")).toBeNull();
    }
  });
});
