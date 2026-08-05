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

  it("renders actionable field information for a Pydantic 422 detail array", async () => {
    const response = jsonResponse(
      { detail: [{ loc: ["body", "name"], msg: "field required" }] },
      { status: 422, statusText: "Unprocessable Entity" },
    );

    const error = await throwApiError(response).catch((err: unknown) => err as ApiError);
    expect(error.message).toContain("body.name");
    expect(error.message).toContain("field required");
    expect(error.message).not.toContain("[object Object]");
    expect(error.message).not.toBe("422 Unprocessable Entity");
    expect(error.status).toBe(422);
  });

  it("joins multiple validation errors and indexes array locations", async () => {
    const response = jsonResponse(
      {
        detail: [
          { loc: ["body", "name"], msg: "field required" },
          { loc: ["body", "agents", 0, "model"], msg: "unexpected value" },
        ],
      },
      { status: 422, statusText: "Unprocessable Entity" },
    );

    const error = await throwApiError(response).catch((err: unknown) => err as ApiError);
    expect(error.message).toBe("body.name: field required; body.agents[0].model: unexpected value");
  });

  it("never leaks the submitted input value from a validation detail", async () => {
    const secret = "hunter2-super-secret-token";
    const response = jsonResponse(
      {
        detail: [
          {
            loc: ["body", "password"],
            msg: "string too short",
            type: "string_too_short",
            input: secret,
            ctx: { min_length: 32 },
          },
        ],
      },
      { status: 422, statusText: "Unprocessable Entity" },
    );

    const error = await throwApiError(response).catch((err: unknown) => err as ApiError);
    expect(error.message).toBe("body.password: string too short");
    expect(error.message).not.toContain(secret);
    expect(error.message).not.toContain("min_length");
    expect(error.message).not.toContain("string_too_short");
  });

  const MALFORMED_CASES: { name: string; detail: unknown; expected: string }[] = [
    { name: "empty array", detail: [], expected: "422 Unprocessable Entity" },
    { name: "non-object entries", detail: [null, 42, true], expected: "422 Unprocessable Entity" },
    { name: "missing msg", detail: [{ loc: ["body", "a"] }], expected: "422 Unprocessable Entity" },
    { name: "empty msg", detail: [{ msg: "" }], expected: "422 Unprocessable Entity" },
    { name: "msg without loc", detail: [{ msg: "no location" }], expected: "no location" },
    {
      name: "loc is not an array",
      detail: [{ loc: "not-an-array", msg: "bad loc type" }],
      expected: "bad loc type",
    },
    { name: "empty loc", detail: [{ loc: [], msg: "empty loc" }], expected: "empty loc" },
    {
      name: "unusable loc parts",
      detail: [{ loc: [null, {}], msg: "unusable loc parts" }],
      expected: "unusable loc parts",
    },
    { name: "plain string entry", detail: ["plain string entry"], expected: "plain string entry" },
    {
      name: "usable entries survive alongside junk",
      detail: [{ loc: ["body"], msg: "kept" }, null, { msg: "also kept" }],
      expected: "body: kept; also kept",
    },
  ];

  it.each(MALFORMED_CASES)(
    "tolerates malformed validation entries without throwing: $name",
    async ({ detail, expected }) => {
      const response = jsonResponse(
        { detail },
        { status: 422, statusText: "Unprocessable Entity" },
      );

      const error = await throwApiError(response).catch((err: unknown) => err as ApiError);
      expect(error).toBeInstanceOf(ApiError);
      expect(error.message).toBe(expected);
      expect(error.message).not.toContain("[object Object]");
    },
  );

  it("does not derive a failure_code from a validation detail array", async () => {
    const response = jsonResponse(
      { detail: [{ loc: ["body", "name"], msg: "field required" }] },
      { status: 422, statusText: "Unprocessable Entity" },
    );

    await expect(throwApiError(response)).rejects.toMatchObject({ failure_code: undefined });
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

  // failure_code chain: body.failure_code > nested.failure_code > nested.code > detail.code.
  // Each case keeps ONLY the level under test and the one below it, so no higher
  // level can short-circuit the assertion.
  describe("failure_code precedence, one adjacent pair at a time", () => {
    it("body.failure_code beats nested.failure_code", async () => {
      const response = jsonResponse(
        { failure_code: "top_level_code", error: { failure_code: "nested_failure_code" } },
        { status: 403, statusText: "Forbidden" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        failure_code: "top_level_code",
      });
    });

    it("nested.failure_code beats nested.code", async () => {
      const response = jsonResponse(
        { error: { failure_code: "nested_failure_code", code: "nested_code" } },
        { status: 403, statusText: "Forbidden" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        failure_code: "nested_failure_code",
      });
    });

    it("nested.code beats detail.code", async () => {
      const response = jsonResponse(
        { error: { code: "nested_code" }, detail: { code: "detail_code", message: "boom" } },
        { status: 403, statusText: "Forbidden" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        failure_code: "nested_code",
      });
    });

    it("detail.code is used when nothing above it is present", async () => {
      const response = jsonResponse(
        { detail: { code: "detail_code", message: "boom" } },
        { status: 403, statusText: "Forbidden" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        failure_code: "detail_code",
      });
    });
  });

  // message chain: nested.message > body.message > detail.message > provision_error > status line.
  describe("message precedence, one adjacent pair at a time", () => {
    it("nested.message beats body.message", async () => {
      const response = jsonResponse(
        { error: { message: "Nested wins" }, message: "Top-level loses" },
        { status: 400, statusText: "Bad Request" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({ message: "Nested wins" });
    });

    it("body.message beats detail.message", async () => {
      const response = jsonResponse(
        { message: "Top-level wins", detail: { message: "Detail loses" } },
        { status: 400, statusText: "Bad Request" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({ message: "Top-level wins" });
    });

    it("detail.message beats provision_error", async () => {
      const response = jsonResponse(
        { detail: { message: "Detail wins" }, provision_error: "provisioning loses" },
        { status: 503, statusText: "Service Unavailable" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        message: "Detail wins",
        provision_error: "provisioning loses",
      });
    });

    it("a validation detail array also beats provision_error", async () => {
      const response = jsonResponse(
        {
          detail: [{ loc: ["body", "name"], msg: "field required" }],
          provision_error: "provisioning loses",
        },
        { status: 422, statusText: "Unprocessable Entity" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        message: "body.name: field required",
      });
    });

    it("provision_error beats the status line", async () => {
      const response = jsonResponse(
        { provision_error: "provisioning wins" },
        { status: 503, statusText: "Service Unavailable" },
      );

      await expect(throwApiError(response)).rejects.toMatchObject({
        message: "provisioning wins",
      });
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
