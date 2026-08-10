import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("@/lib/CapabilitiesContext", () => ({
  useServerInfo: () => ({ accounts_enabled: false, needs_setup: false }),
}));

vi.mock("@/shell/AppShell", () => ({
  AppShell: () => {
    const location = useLocation();
    return (
      <>
        <output data-testid="route-path">{location.pathname}</output>
        <Outlet />
      </>
    );
  },
}));

vi.mock("@/pages/ChatPage", () => ({ ChatPage: () => <div>Chat page</div> }));
vi.mock("@/pages/NotFoundPage", () => ({ NotFoundPage: () => <div>Not found</div> }));
vi.mock("@/pages/AutomationsPage", () => ({
  AutomationsPage: () => <div>Automations page</div>,
}));

afterEach(() => cleanup());

describe("App Automations routes", () => {
  it("renders Automations at its canonical route", async () => {
    render(
      <MemoryRouter initialEntries={["/automations"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Automations page")).toBeInTheDocument();
    expect(screen.getByTestId("route-path")).toHaveTextContent("/automations");
  });

  it("replaces the legacy /tasks route with /automations", async () => {
    render(
      <MemoryRouter initialEntries={["/tasks"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("route-path")).toHaveTextContent("/automations");
    });
    expect(screen.getByText("Automations page")).toBeInTheDocument();
  });

  it("preserves the embed basename when redirecting /tasks", async () => {
    render(
      <MemoryRouter initialEntries={["/ml/orvia/tasks"]}>
        <App basename="/ml/orvia" />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("route-path")).toHaveTextContent("/ml/orvia/automations");
    });
    expect(screen.getByText("Automations page")).toBeInTheDocument();
  });
});
