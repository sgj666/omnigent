import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getUsageReport } from "@/lib/usageApi";
import { UsagePage } from "./UsagePage";

vi.mock("@/lib/usageApi", () => ({ getUsageReport: vi.fn() }));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(initialEntry = "/usage") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <UsagePage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUsageReport).mockResolvedValue({
    object: "usage_report",
    cost_today: 1,
    cost_last_7d: 2,
    cost_last_30d: 3,
    total_cost_usd: 4,
    daily_cost: [
      { day_utc: "2026-08-05", cost_usd: 0.25 },
      { day_utc: "2026-08-06", cost_usd: 0.5 },
      { day_utc: "2026-08-07", cost_usd: 0.75 },
    ],
    sessions: [
      {
        id: "session-1",
        title: "Research run",
        created_at: 100,
        updated_at: 200,
        cost_usd: 0.25,
        priced: true,
        input_tokens: 700,
        output_tokens: 300,
        cache_read_input_tokens: 0,
        total_tokens: 1000,
        models: { "gpt-5.6": 0.25 },
      },
    ],
    operations: {
      total_tasks: 1,
      total_runs: 1,
      active_runs: 0,
      terminal_runs: 1,
      succeeded_runs: 1,
      failed_runs: 0,
      cancelled_runs: 0,
      waiting_runs: 0,
      success_rate: 1,
      retry_runs: 0,
      retry_rate: 0,
      average_queue_seconds: 5,
      average_run_seconds: 30,
      priced_runs: 1,
      unpriced_runs: 0,
      waiting_duration_available: false,
    },
    breakdowns: {
      projects: [
        {
          id: "project-1",
          name: "Launch",
          run_count: 1,
          succeeded_runs: 1,
          failed_runs: 0,
          success_rate: 1,
          cost_usd: 0.25,
          priced_run_count: 1,
          unpriced_run_count: 0,
          total_tokens: 1000,
          average_run_seconds: 30,
          uses: null,
          cost_attribution: "session",
        },
      ],
      agents: [],
      runtimes: [],
      skills: [],
    },
    filter_options: {
      projects: [{ id: "project-1", name: "Launch" }],
      agents: [{ id: "agent-1", name: "Polly" }],
    },
    task_runs: [
      {
        id: "run-1",
        task_id: "task-1",
        task_title: "Ship launch",
        project_id: "project-1",
        project_name: "Launch",
        agent_id: "agent-1",
        agent_name: "Polly",
        runtime_id: "runtime-1",
        runtime_name: "MacBook Pro",
        session_id: "session-1",
        state: "succeeded",
        trigger: "manual",
        retry_of_run_id: null,
        queued_at: 100,
        started_at: 105,
        finished_at: 135,
        queue_seconds: 5,
        run_seconds: 30,
        run_duration_live: false,
        priced: true,
        cost_usd: 0.25,
        input_tokens: 700,
        output_tokens: 300,
        cache_read_input_tokens: 0,
        total_tokens: 1000,
        observed_skills: [],
        waiting_reason: null,
        failure_code: null,
        failure_message: null,
      },
    ],
  });
});

describe("UsagePage", () => {
  it("renders authoritative cost windows and cumulative session tokens", async () => {
    renderPage();
    expect(await screen.findByText("Research run")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.6")).toBeInTheDocument();
    expect(screen.getAllByText("1,000").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("$0.25").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Operational metrics")).toBeInTheDocument();
    expect(screen.getByText("Ship launch")).toBeInTheDocument();
    expect(screen.getAllByText("Polly").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("img", { name: /Daily usage trend: \$1\.50/ })).toBeInTheDocument();
  });

  it("filters session rows by model", async () => {
    renderPage();
    await screen.findByText("Research run");
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), {
      target: { value: "not-a-model" },
    });
    await waitFor(() =>
      expect(screen.getByText("No sessions match this search")).toBeInTheDocument(),
    );
  });

  it("restores TaskRun filters from the URL and keeps changes in the URL", async () => {
    renderPage("/usage?range=7d&project=project-1&agent=agent-1&by=agents");
    await screen.findByText("Research run");

    expect(vi.mocked(getUsageReport).mock.calls[0][0]).toEqual({
      range: "7d",
      projectId: "project-1",
      agentId: "agent-1",
    });
    expect(screen.getByRole("combobox", { name: "Project filter" })).toHaveValue("project-1");
    expect(screen.getByRole("combobox", { name: "Agent filter" })).toHaveValue("agent-1");
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/usage?range=7d&project=project-1&agent=agent-1&by=agents",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Project filter" }), {
      target: { value: "" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).not.toContain("project="),
    );
    expect(screen.getByTestId("location")).toHaveTextContent("range=7d");
    expect(screen.getByTestId("location")).toHaveTextContent("agent=agent-1");
  });

  it("shows a dedicated permission state for a forbidden report", async () => {
    vi.mocked(getUsageReport).mockRejectedValue(new Error("403 Forbidden"));

    renderPage();

    expect(await screen.findByText("You don’t have access to this collection")).toBeInTheDocument();
  });
});
