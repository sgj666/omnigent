import { beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import { getUsageReport } from "./usageApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

beforeEach(() => vi.mocked(authenticatedFetch).mockReset());

describe("getUsageReport", () => {
  it("reads the typed usage report", async () => {
    const payload = {
      object: "usage_report" as const,
      cost_today: 1,
      cost_last_7d: 2,
      cost_last_30d: 3,
      total_cost_usd: 4,
      sessions: [],
    };
    vi.mocked(authenticatedFetch).mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    );

    await expect(
      getUsageReport({ range: "7d", projectId: "project/1", agentId: "agent 1" }),
    ).resolves.toEqual(payload);
    expect(authenticatedFetch).toHaveBeenCalledWith(
      "/v1/usage?range=7d&project_id=project%2F1&agent_id=agent+1",
      { signal: undefined },
    );
  });

  it("rejects non-success responses", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(new Response(null, { status: 503 }));
    await expect(getUsageReport({ range: "30d" })).rejects.toThrow("503");
  });
});
