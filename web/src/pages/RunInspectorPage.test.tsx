import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runEvaluationFixture, runInspectorFixture } from "@/lib/runsApi.fixture";
import { parseRunEvaluationResponse, parseRunInspectorResponse } from "@/lib/runsApi";
import { RunInspectorPage } from "./RunInspectorPage";

const ROUTER_FUTURE_FLAGS = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
} as const;

const useRunMock = vi.fn();
const useRunEvaluationMock = vi.fn();
const refreshMock = vi.fn();
const refreshStateMock = vi.fn();

vi.mock("@/hooks/useRuns", () => ({
  useRun: () => useRunMock(),
  useRunEvaluation: () => useRunEvaluationMock(),
  useRefreshRunEvaluation: () => refreshStateMock(),
}));

function page() {
  return (
    <MemoryRouter initialEntries={["/runs/run-1"]} future={ROUTER_FUTURE_FLAGS}>
      <Routes>
        <Route path="/runs/:runId" element={<RunInspectorPage />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderPage() {
  return render(page());
}

beforeEach(() => {
  refreshMock.mockReset();
  refreshStateMock.mockReturnValue({
    mutate: refreshMock,
    isPending: false,
    isError: false,
    error: null,
  });
});

describe("RunInspectorPage", () => {
  it("shows the bounded Core Inspector with the nested Run title", () => {
    useRunMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: parseRunInspectorResponse(runInspectorFixture),
    });
    useRunEvaluationMock.mockReturnValue({
      data: parseRunEvaluationResponse(runEvaluationFixture),
      isError: false,
    });

    renderPage();

    expect(screen.getByRole("heading", { name: "Run run-1" })).toBeVisible();
    expect(screen.getByText("/work/checkout")).toBeVisible();
    expect(screen.getByText("Task DAG")).toBeVisible();
    expect(screen.getByText("TEST_COMMAND_EXIT_1")).toBeVisible();
    expect(screen.getByText("Coordinator Parent Inbox")).toBeVisible();
    expect(screen.getByText("sha256:abcdef0123456789")).toBeVisible();
    expect(screen.getByText("Root & child sessions")).toBeVisible();
    expect(screen.getByRole("link", { name: "session-root" })).toBeVisible();
    expect(screen.getByText("The focused test command exited with status 1")).toBeVisible();
    expect(screen.getByRole("link", { name: /multi-agent/i })).toHaveAttribute(
      "href",
      "/multi-agents",
    );
  });

  it("keeps the Inspector visible when evaluation loading fails", () => {
    useRunMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: parseRunInspectorResponse(runInspectorFixture),
    });
    useRunEvaluationMock.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("evaluation unavailable"),
    });

    renderPage();

    expect(screen.getByText("run-1")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("evaluation unavailable");
  });

  it("keeps cached evaluation visible and scopes refresh errors to the evaluation card", () => {
    useRunMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: parseRunInspectorResponse(runInspectorFixture),
    });
    useRunEvaluationMock.mockReturnValue({
      data: parseRunEvaluationResponse(runEvaluationFixture),
      isError: false,
    });
    refreshStateMock.mockReturnValue({
      mutate: refreshMock,
      isPending: false,
      isError: true,
      error: new Error("refresh unavailable"),
    });

    const view = renderPage();

    expect(screen.getByText("50%")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("refresh unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Refresh evaluation" }));
    expect(refreshMock).toHaveBeenCalledWith("run-1");

    refreshStateMock.mockReturnValue({
      mutate: refreshMock,
      isPending: true,
      isError: false,
      error: null,
    });
    view.rerender(page());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("50%")).toBeVisible();

    refreshStateMock.mockReturnValue({
      mutate: refreshMock,
      isPending: false,
      isError: false,
      error: null,
    });
    view.rerender(page());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("50%")).toBeVisible();
  });
});
