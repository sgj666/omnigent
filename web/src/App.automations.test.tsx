import { cleanup, render, screen } from "@testing-library/react";
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
vi.mock("@/pages/TasksPage", () => ({ TasksPage: () => <div>Tasks page</div> }));

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

  it("renders the product Task board at /tasks", async () => {
    render(
      <MemoryRouter initialEntries={["/tasks"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Tasks page")).toBeInTheDocument();
    expect(screen.getByTestId("route-path")).toHaveTextContent("/tasks");
  });

  it("preserves the embed basename for /tasks", async () => {
    render(
      <MemoryRouter initialEntries={["/ml/orvia/tasks"]}>
        <App basename="/ml/orvia" />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Tasks page")).toBeInTheDocument();
    expect(screen.getByTestId("route-path")).toHaveTextContent("/ml/orvia/tasks");
  });
});
