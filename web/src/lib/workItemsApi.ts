import { authenticatedFetch } from "./identity";
import type { TaskRunState, TaskState } from "./workLifecycle";

export const WORK_ITEM_PRIORITIES = ["low", "medium", "high", "urgent"] as const;
export type WorkItemPriority = (typeof WORK_ITEM_PRIORITIES)[number];

export interface WorkItem {
  id: string;
  object: "work_item";
  title: string;
  description: string | null;
  state: TaskState;
  priority: WorkItemPriority;
  project_id: string | null;
  assignee_agent_id: string | null;
  due_at: number | null;
  created_at: number;
  updated_at: number | null;
  completed_at: number | null;
  creator_kind?: "user" | "agent" | "automation";
  created_by_agent_id?: string | null;
  version: number;
}

export interface CreateWorkItemInput {
  title: string;
  description?: string;
  state?: TaskState;
  priority?: WorkItemPriority;
  project_id?: string;
  assignee_agent_id?: string;
  due_at?: number;
}

export type UpdateWorkItemInput = Partial<Omit<CreateWorkItemInput, "state">> & {
  state?: TaskState;
  expected_version: number;
};

export interface WorkItemRunFailure {
  code: string;
  message: string;
  retryable: boolean;
}

export interface WorkItemRun {
  id: string;
  object: "work_item_run";
  work_item_id: string;
  session_id: string | null;
  agent_id: string;
  runtime_id: string;
  workspace: string;
  state: TaskRunState;
  trigger: "manual" | "retry";
  retry_of_run_id: string | null;
  queued_at: number;
  started_at: number | null;
  finished_at: number | null;
  updated_at: number | null;
  result_summary: string | null;
  failure: WorkItemRunFailure | null;
  artifact_refs: string[];
  usage_refs: string[];
}

export interface CreateWorkItemRunInput {
  runtime_id: string;
  workspace: string;
  retry_of_run_id?: string;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export async function listWorkItems(): Promise<WorkItem[]> {
  const response = await authenticatedFetch("/v1/work-items");
  if (!response.ok) throw new Error(await readError(response));
  const body = (await response.json()) as { object: "list"; data: WorkItem[] };
  return body.data;
}

export async function getWorkItem(id: string): Promise<WorkItem> {
  const response = await authenticatedFetch(`/v1/work-items/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as WorkItem;
}

export async function createWorkItem(input: CreateWorkItemInput): Promise<WorkItem> {
  const response = await authenticatedFetch("/v1/work-items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as WorkItem;
}

export async function updateWorkItem(id: string, input: UpdateWorkItemInput): Promise<WorkItem> {
  const response = await authenticatedFetch(`/v1/work-items/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as WorkItem;
}

export async function listWorkItemRuns(workItemId: string): Promise<WorkItemRun[]> {
  const response = await authenticatedFetch(
    `/v1/work-items/${encodeURIComponent(workItemId)}/runs`,
  );
  if (!response.ok) throw new Error(await readError(response));
  const body = (await response.json()) as { object: "list"; data: WorkItemRun[] };
  return body.data;
}

export async function createWorkItemRun(
  workItemId: string,
  input: CreateWorkItemRunInput,
): Promise<WorkItemRun> {
  const response = await authenticatedFetch(
    `/v1/work-items/${encodeURIComponent(workItemId)}/runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as WorkItemRun;
}

export async function cancelWorkItemRun(workItemId: string, runId: string): Promise<WorkItemRun> {
  const response = await authenticatedFetch(
    `/v1/work-items/${encodeURIComponent(workItemId)}/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as WorkItemRun;
}
