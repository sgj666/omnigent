import { beforeEach, describe, expect, it, vi } from "vitest";

import { authenticatedFetch } from "./identity";
import {
  cancelWorkItemRun,
  createWorkItem,
  createWorkItemRun,
  getWorkItem,
  listWorkItemRuns,
  listWorkItems,
  updateWorkItem,
} from "./workItemsApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

const item = {
  id: "task_1",
  object: "work_item" as const,
  title: "Ship board",
  description: null,
  state: "backlog" as const,
  priority: "medium" as const,
  project_id: null,
  assignee_agent_id: null,
  due_at: null,
  created_at: 1,
  updated_at: null,
  completed_at: null,
  version: 1,
};

const run = {
  id: "run_1",
  object: "work_item_run" as const,
  work_item_id: "task_1",
  session_id: "session_1",
  agent_id: "agent_1",
  runtime_id: "runtime_1",
  workspace: "/workspace",
  state: "running" as const,
  trigger: "manual" as const,
  retry_of_run_id: null,
  queued_at: 1,
  started_at: 2,
  finished_at: null,
  updated_at: 2,
  result_summary: null,
  failure: null,
  artifact_refs: [],
  usage_refs: ["session:session_1"],
};

beforeEach(() => vi.mocked(authenticatedFetch).mockReset());

describe("workItemsApi", () => {
  it("lists and gets product Tasks", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ object: "list", data: [item] }),
      } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => item } as Response);

    await expect(listWorkItems()).resolves.toEqual([item]);
    await expect(getWorkItem("task_1")).resolves.toEqual(item);
    expect(authenticatedFetch).toHaveBeenNthCalledWith(1, "/v1/work-items");
    expect(authenticatedFetch).toHaveBeenNthCalledWith(2, "/v1/work-items/task_1");
  });

  it("creates and version-updates a product Task", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce({ ok: true, json: async () => item } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ...item, state: "todo", version: 2 }),
      } as Response);

    await createWorkItem({ title: "Ship board" });
    await updateWorkItem("task_1", { state: "todo", expected_version: 1 });

    expect(authenticatedFetch).toHaveBeenNthCalledWith(
      1,
      "/v1/work-items",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "Ship board" }) }),
    );
    expect(authenticatedFetch).toHaveBeenNthCalledWith(
      2,
      "/v1/work-items/task_1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ state: "todo", expected_version: 1 }),
      }),
    );
  });

  it("surfaces the server conflict message", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ error: { message: "Task changed since version 1" } }),
    } as Response);

    await expect(updateWorkItem("task_1", { state: "done", expected_version: 1 })).rejects.toThrow(
      "Task changed since version 1",
    );
  });

  it("lists, starts, and cancels TaskRuns", async () => {
    vi.mocked(authenticatedFetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ object: "list", data: [run] }),
      } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => run } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ...run, state: "cancelled" }),
      } as Response);

    await expect(listWorkItemRuns("task_1")).resolves.toEqual([run]);
    await createWorkItemRun("task_1", {
      runtime_id: "runtime_1",
      workspace: "/workspace",
    });
    await cancelWorkItemRun("task_1", "run_1");

    expect(authenticatedFetch).toHaveBeenNthCalledWith(1, "/v1/work-items/task_1/runs");
    expect(authenticatedFetch).toHaveBeenNthCalledWith(
      2,
      "/v1/work-items/task_1/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ runtime_id: "runtime_1", workspace: "/workspace" }),
      }),
    );
    expect(authenticatedFetch).toHaveBeenNthCalledWith(
      3,
      "/v1/work-items/task_1/runs/run_1/cancel",
      { method: "POST" },
    );
  });
});
