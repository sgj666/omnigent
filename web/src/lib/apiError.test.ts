import { describe, expect, it } from "vitest";
import { throwApiError } from "./apiError";

describe("throwApiError", () => {
  it("renders structured FastAPI detail instead of object coercion", async () => {
    const response = new Response(
      JSON.stringify({
        detail: {
          code: "feishu_integration_unavailable",
          message: "Standalone Feishu integration is unavailable",
        },
      }),
      { status: 503, statusText: "Service Unavailable" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "Standalone Feishu integration is unavailable",
      failure_code: "feishu_integration_unavailable",
      status: 503,
    });
  });
});
