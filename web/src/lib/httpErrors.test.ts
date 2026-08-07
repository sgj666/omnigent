import { describe, expect, it } from "vitest";
import { isPermissionDenied } from "./httpErrors";

describe("isPermissionDenied", () => {
  it("recognizes status-bearing and plain HTTP permission errors", () => {
    expect(isPermissionDenied(Object.assign(new Error("Denied"), { status: 403 }))).toBe(true);
    expect(isPermissionDenied(new Error("401 Unauthorized"))).toBe(true);
    expect(isPermissionDenied(new Error("Permission denied"))).toBe(true);
  });

  it("does not classify unrelated failures as permission errors", () => {
    expect(isPermissionDenied(new Error("500 Internal Server Error"))).toBe(false);
    expect(isPermissionDenied(undefined)).toBe(false);
  });
});
