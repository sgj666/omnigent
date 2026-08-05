import { describe, expect, it } from "vitest";
import { ApiError, throwApiError } from "./apiError";

function jsonResponse(
  body: unknown,
  init: ResponseInit & { headers?: Record<string, string> } = {},
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 500,
    statusText: init.statusText ?? "Internal Server Error",
    headers: init.headers,
  });
}

describe("throwApiError", () => {
  it("renders structured FastAPI detail instead of object coercion", async () => {
    const response = jsonResponse(
      {
        detail: {
          code: "feishu_integration_unavailable",
          message: "Standalone Feishu integration is unavailable",
        },
      },
      { status: 503, statusText: "Service Unavailable" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "Standalone Feishu integration is unavailable",
      failure_code: "feishu_integration_unavailable",
      status: 503,
    });
  });

  it("never stringifies a structured detail into [object Object]", async () => {
    const response = jsonResponse(
      { detail: { code: "feishu_integration_timeout", message: "Upstream timed out" } },
      { status: 504, statusText: "Gateway Timeout" },
    );

    const error = await throwApiError(response).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).not.toContain("[object Object]");
    expect((error as ApiError).message).toBe("Upstream timed out");
  });

  it("keeps supporting a plain string detail", async () => {
    const response = jsonResponse(
      { detail: "Agent not found" },
      { status: 404, statusText: "Not Found" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "Agent not found",
      failure_code: undefined,
      status: 404,
    });
  });

  it("falls back to the status line when detail is missing", async () => {
    const response = jsonResponse({}, { status: 500, statusText: "Internal Server Error" });

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "500 Internal Server Error",
      status: 500,
    });
  });

  it("falls back to the status line when detail is an unexpected array", async () => {
    const response = jsonResponse(
      { detail: [{ loc: ["body", "name"], msg: "field required" }] },
      { status: 422, statusText: "Unprocessable Entity" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "422 Unprocessable Entity",
      failure_code: undefined,
      status: 422,
    });
  });

  it("falls back to the status line when detail is null", async () => {
    const response = jsonResponse({ detail: null }, { status: 502, statusText: "Bad Gateway" });

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "502 Bad Gateway",
      failure_code: undefined,
      status: 502,
    });
  });

  it("prefers the nested error message over detail and top-level message", async () => {
    const response = jsonResponse(
      {
        error: {
          message: "Nested wins",
          code: "nested_code",
          provision_error: "nested provisioning failed",
          request_id: "req-nested",
        },
        message: "Top-level loses",
        detail: { code: "detail_code", message: "Detail loses" },
      },
      { status: 400, statusText: "Bad Request" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "Nested wins",
      failure_code: "nested_code",
      provision_error: "nested provisioning failed",
      request_id: "req-nested",
      status: 400,
    });
  });

  it("prefers the top-level message over a structured detail message", async () => {
    const response = jsonResponse(
      { message: "Top-level wins", detail: { code: "detail_code", message: "Detail loses" } },
      { status: 409, statusText: "Conflict" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "Top-level wins",
      failure_code: "detail_code",
      status: 409,
    });
  });

  it("uses the detail code only as the last failure_code fallback", async () => {
    const response = jsonResponse(
      {
        failure_code: "top_level_code",
        error: { failure_code: "nested_code" },
        detail: { code: "detail_code", message: "boom" },
      },
      { status: 403, statusText: "Forbidden" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      failure_code: "top_level_code",
      status: 403,
    });
  });

  it("falls back to provision_error when no message or detail is present", async () => {
    const response = jsonResponse(
      { provision_error: "workspace provisioning failed" },
      { status: 503, statusText: "Service Unavailable" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "workspace provisioning failed",
      provision_error: "workspace provisioning failed",
      status: 503,
    });
  });

  it("prefers the X-Request-Id header over body request ids", async () => {
    const response = jsonResponse(
      { request_id: "body-req", detail: "nope" },
      { status: 500, headers: { "X-Request-Id": "header-req" } },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({ request_id: "header-req" });
  });

  it("keeps the status line when the body is not JSON", async () => {
    const response = new Response("<html>gateway</html>", {
      status: 502,
      statusText: "Bad Gateway",
    });

    await expect(throwApiError(response)).rejects.toMatchObject({
      message: "502 Bad Gateway",
      status: 502,
    });
  });
});
