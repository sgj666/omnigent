import { afterEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "@/lib/identity";
import { ApiError, listTeams } from "@/lib/teamsApi";

vi.mock("@/lib/identity", () => ({ authenticatedFetch: vi.fn() }));

describe("team API client", () => {
  afterEach(() => vi.clearAllMocks());

  it("loads teams through authenticatedFetch", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(
      new Response(JSON.stringify({ object: "list", data: [{ id: "team-1", name: "Core" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(listTeams()).resolves.toEqual([{ id: "team-1", name: "Core" }]);
    expect(authenticatedFetch).toHaveBeenCalledWith("/v1/teams");
  });

  it("retains structured failure details and request id", async () => {
    vi.mocked(authenticatedFetch).mockResolvedValue(
      new Response(JSON.stringify({ failure_code: "TEAM_PROVISION_FAILED", provision_error: "quota" }), {
        status: 502,
        headers: { "X-Request-Id": "req-1" },
      }),
    );

    const error = await listTeams().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 502,
      failure_code: "TEAM_PROVISION_FAILED",
      provision_error: "quota",
      request_id: "req-1",
    });
  });
});

