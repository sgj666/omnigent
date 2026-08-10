import { describe, expect, it } from "vitest";
import { APP_ROUTES, getGlobalNavigationItem, GLOBAL_NAVIGATION } from "./navigation";

describe("global navigation registry", () => {
  it("has unique ids and canonical paths", () => {
    expect(new Set(GLOBAL_NAVIGATION.map((item) => item.id)).size).toBe(GLOBAL_NAVIGATION.length);
    expect(new Set(GLOBAL_NAVIGATION.map((item) => item.href)).size).toBe(GLOBAL_NAVIGATION.length);
    expect(getGlobalNavigationItem("automations")).toEqual({
      id: "automations",
      label: "Automations",
      href: APP_ROUTES.automations,
    });
  });

  it("only exposes routes that currently exist", () => {
    expect(GLOBAL_NAVIGATION.map((item) => item.id)).toEqual([
      "chat",
      "inbox",
      "automations",
      "settings",
    ]);
  });
});
