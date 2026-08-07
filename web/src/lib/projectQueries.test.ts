import { describe, expect, it } from "vitest";
import { projectQueryKeys } from "./projectQueries";

describe("project query keys", () => {
  it("keeps collection prefixes stable", () => {
    expect(projectQueryKeys.all).toEqual(["projects"]);
    expect(projectQueryKeys.sessions("Launch")).toEqual(["project-sessions", "Launch"]);
    expect(projectQueryKeys.config("p_1")).toEqual(["project-config", "p_1"]);
    expect(projectQueryKeys.archivedNames).not.toEqual(projectQueryKeys.all);
  });
});
