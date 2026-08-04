import { beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import { runEvaluationFixture, runInspectorFixture } from "./runsApi.fixture";
import {
  approveRunApproval,
  createRun,
  denyRunApproval,
  getRunEvaluation,
  getRunInspector,
  listRunEvents,
  listRuns,
  parseRunEvaluationResponse,
  parseRunInspectorResponse,
  refreshRunEvaluation,
  stopRun,
} from "./runsApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

const fetchMock = vi.mocked(authenticatedFetch);
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("Run API DTO contract", () => {
  beforeEach(() => fetchMock.mockReset());

  it("parses the exact Core inspector and evaluation fixtures", () => {
    expect(parseRunInspectorResponse(runInspectorFixture)).toEqual(runInspectorFixture);
    expect(parseRunEvaluationResponse(runEvaluationFixture)).toEqual(runEvaluationFixture);
  });

  it("rejects extra fields, missing fields, and the obsolete top-level Run shape", () => {
    expect(() =>
      parseRunInspectorResponse({ ...runInspectorFixture, stdout: "must never cross this API" }),
    ).toThrow(/unexpected field.*stdout/i);
    expect(() => parseRunInspectorResponse({ ...runInspectorFixture, tasks: undefined })).toThrow(
      /tasks/i,
    );
    expect(() =>
      parseRunInspectorResponse({
        ...runInspectorFixture,
        run: { ...runInspectorFixture.run, object: "run" },
      }),
    ).toThrow(/unexpected field.*object/i);
    expect(() =>
      parseRunInspectorResponse({ id: "run-1", status: "running", tasks: [], attempts: [] }),
    ).toThrow(/run/i);
  });

  it("maps create, list, inspector, events, control, approval, and evaluation endpoints", async () => {
    const run = { ...runInspectorFixture.run, object: "run" };
    fetchMock
      .mockResolvedValueOnce(json(run, 201))
      .mockResolvedValueOnce(json({ object: "list", data: [run] }))
      .mockResolvedValueOnce(json(runInspectorFixture))
      .mockResolvedValueOnce(json({ object: "list", data: runInspectorFixture.events }))
      .mockResolvedValueOnce(json({ id: "run-1", status: "stopping" }))
      .mockResolvedValueOnce(json({ id: "approval-1", run_id: "run-1", decision: "approve" }))
      .mockResolvedValueOnce(json({ id: "approval-2", run_id: "run-1", decision: "deny" }))
      .mockResolvedValueOnce(json(runEvaluationFixture))
      .mockResolvedValueOnce(json(runEvaluationFixture));

    const input = {
      agent_id: "agent-polly",
      workspace_id: "workspace-1",
      input: "Fix checkout",
      source: "web",
      source_event_id: "web:event-1",
      host_id: "host-1",
      execution_mode: "auto" as const,
    };
    await createRun(input);
    await listRuns();
    await getRunInspector("run 1");
    await listRunEvents("run 1");
    await stopRun("run 1");
    await approveRunApproval("run 1", "approval 1");
    await denyRunApproval("run 1", "approval 2");
    await getRunEvaluation("run 1");
    await refreshRunEvaluation("run 1");

    expect(fetchMock.mock.calls).toEqual([
      [
        "/v1/runs",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        },
      ],
      ["/v1/runs"],
      ["/v1/runs/run%201"],
      ["/v1/runs/run%201/events"],
      ["/v1/runs/run%201/stop", { method: "POST" }],
      ["/v1/runs/run%201/approvals/approval%201/approve", { method: "POST" }],
      ["/v1/runs/run%201/approvals/approval%202/deny", { method: "POST" }],
      ["/v1/runs/run%201/evaluation"],
      [
        "/v1/runs/run%201/evaluation",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh: true }),
        },
      ],
    ]);
  });
});
