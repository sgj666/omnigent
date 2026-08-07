import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("@/lib/CapabilitiesContext", () => ({
  useServerInfo: () => ({ accounts_enabled: false, needs_setup: false }),
}));
vi.mock("@/shell/AppShell", () => ({ AppShell: () => <Outlet /> }));
vi.mock("@/pages/ChatPage", () => ({ ChatPage: () => <div>Chat</div> }));
vi.mock("@/pages/NotFoundPage", () => ({ NotFoundPage: () => <div>Not found</div> }));
vi.mock("@/pages/ProjectsPage", () => ({ ProjectsPage: () => <div>Projects management</div> }));
vi.mock("@/pages/ProjectDetailPage", () => ({
  ProjectDetailPage: () => <div>Project detail</div>,
}));
vi.mock("@/pages/UsagePage", () => ({ UsagePage: () => <div>Usage management</div> }));
vi.mock("@/pages/SkillsPage", () => ({ SkillsPage: () => <div>Skills management</div> }));
vi.mock("@/pages/SkillDetailPage", () => ({
  SkillDetailPage: () => <div>Skill detail</div>,
}));
vi.mock("@/pages/RuntimePage", () => ({ RuntimePage: () => <div>Runtime management</div> }));
vi.mock("@/pages/RuntimeDetailPage", () => ({
  RuntimeDetailPage: () => <div>Runtime detail</div>,
}));
vi.mock("@/pages/TaskDetailPage", () => ({ TaskDetailPage: () => <div>Task detail</div> }));

afterEach(() => cleanup());

describe("App management routes", () => {
  it.each([
    ["/projects", "Projects management"],
    ["/usage", "Usage management"],
    ["/runtime", "Runtime management"],
    ["/skills", "Skills management"],
  ])("renders %s", async (path, label) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it.each([
    ["/ml/orvia/projects", "Projects management"],
    ["/ml/orvia/usage", "Usage management"],
    ["/ml/orvia/runtime", "Runtime management"],
    ["/ml/orvia/skills", "Skills management"],
  ])("preserves the embed basename for %s", async (path, label) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App basename="/ml/orvia" />
      </MemoryRouter>,
    );
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it.each([
    ["/projects/project-1", "Project detail", undefined],
    ["/runtime/host-1", "Runtime detail", undefined],
    ["/tasks/task-1", "Task detail", undefined],
    ["/skills/skill-1", "Skill detail", undefined],
    ["/ml/orvia/projects/project-1", "Project detail", "/ml/orvia"],
    ["/ml/orvia/runtime/host-1", "Runtime detail", "/ml/orvia"],
    ["/ml/orvia/tasks/task-1", "Task detail", "/ml/orvia"],
    ["/ml/orvia/skills/skill-1", "Skill detail", "/ml/orvia"],
  ])("renders the management detail route %s", async (path, label, basename) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App basename={basename} />
      </MemoryRouter>,
    );
    expect(await screen.findByText(label)).toBeInTheDocument();
  });
});
