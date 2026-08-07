import { authenticatedFetch } from "./identity";

export interface SessionUsage {
  id: string;
  created_at: number;
  updated_at: number;
  title: string | null;
  cost_usd: number;
  priced: boolean;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  total_tokens: number;
  models: Record<string, number>;
}

export interface OperationalUsageMetrics {
  total_tasks: number;
  total_runs: number;
  active_runs: number;
  terminal_runs: number;
  succeeded_runs: number;
  failed_runs: number;
  cancelled_runs: number;
  waiting_runs: number;
  success_rate: number | null;
  retry_runs: number;
  retry_rate: number | null;
  average_queue_seconds: number | null;
  average_run_seconds: number | null;
  priced_runs: number;
  unpriced_runs: number;
  waiting_duration_available: boolean;
}

export interface UsageBreakdownRow {
  id: string;
  name: string;
  run_count: number;
  succeeded_runs: number;
  failed_runs: number;
  success_rate: number | null;
  cost_usd: number;
  priced_run_count: number;
  unpriced_run_count: number;
  total_tokens: number;
  average_run_seconds: number | null;
  uses: number | null;
  cost_attribution: "session" | "session_association_only";
}

export interface UsageBreakdowns {
  projects: UsageBreakdownRow[];
  agents: UsageBreakdownRow[];
  runtimes: UsageBreakdownRow[];
  skills: UsageBreakdownRow[];
}

export interface UsageFilterOption {
  id: string;
  name: string;
}

export interface UsageFilterOptions {
  projects: UsageFilterOption[];
  agents: UsageFilterOption[];
}

export interface TaskRunUsage {
  id: string;
  task_id: string;
  task_title: string;
  project_id: string | null;
  project_name: string | null;
  agent_id: string;
  agent_name: string;
  runtime_id: string;
  runtime_name: string;
  session_id: string | null;
  state: "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";
  trigger: "manual" | "retry";
  retry_of_run_id: string | null;
  queued_at: number;
  started_at: number | null;
  finished_at: number | null;
  queue_seconds: number | null;
  run_seconds: number | null;
  run_duration_live: boolean;
  priced: boolean;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  total_tokens: number;
  observed_skills: string[];
  waiting_reason: string | null;
  failure_code: string | null;
  failure_message: string | null;
}

export interface UsageReport {
  object: "usage_report";
  cost_today: number;
  cost_last_7d: number;
  cost_last_30d: number;
  total_cost_usd: number;
  daily_cost?: { day_utc: string; cost_usd: number }[];
  sessions: SessionUsage[];
  operations: OperationalUsageMetrics;
  breakdowns: UsageBreakdowns;
  filter_options: UsageFilterOptions;
  task_runs: TaskRunUsage[];
}

export interface UsageReportFilters {
  range: "today" | "7d" | "30d" | "all";
  projectId?: string;
  agentId?: string;
}

export async function getUsageReport(
  filters: UsageReportFilters,
  signal?: AbortSignal,
): Promise<UsageReport> {
  const params = new URLSearchParams({ range: filters.range });
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.agentId) params.set("agent_id", filters.agentId);
  const response = await authenticatedFetch(`/v1/usage?${params}`, { signal });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as UsageReport;
}
