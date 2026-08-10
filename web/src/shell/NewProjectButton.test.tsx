import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NewProjectButton } from "./NewProjectButton";

const { mutateMock, useHostsMock } = vi.hoisted(() => ({
  mutateMock: vi.fn(),
  useHostsMock: vi.fn(),
}));

vi.mock("@/hooks/useConversations", () => ({
  useCreateProject: () => ({
    mutate: mutateMock,
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/hooks/useHosts", () => ({
  useHosts: useHostsMock,
}));

vi.mock("./WorkspacePicker", () => ({
  isNavigablePath: (path: string) => path.startsWith("/"),
  WorkspacePicker: ({
    hostId,
    onNavigate,
  }: {
    hostId: string;
    onNavigate: (p: string) => void;
  }) => (
    <button type="button" data-testid="pick-project-folder" onClick={() => onNavigate("/repo/app")}>
      pick on {hostId}
    </button>
  ),
}));

function renderButton(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <NewProjectButton onCreated={onCreated} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return onCreated;
}

beforeEach(() => {
  mutateMock.mockReset();
  useHostsMock.mockReset();
  useHostsMock.mockReturnValue({
    data: [{ host_id: "host_1", name: "Laptop", owner: "me", status: "online" }],
  });
});

describe("NewProjectButton", () => {
  it("creates a Project with its host and source folder bound", async () => {
    const onCreated = renderButton();
    fireEvent.click(screen.getByTestId("new-project"));

    fireEvent.change(screen.getByPlaceholderText("Project name…"), {
      target: { value: "Alpha" },
    });
    await waitFor(() => expect(screen.getByTestId("pick-project-folder")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pick-project-folder"));
    fireEvent.click(screen.getByTestId("new-project-confirm"));

    expect(mutateMock).toHaveBeenCalledTimes(1);
    const [variables, options] = mutateMock.mock.calls[0];
    expect(variables).toEqual({
      name: "Alpha",
      config: { host_id: "host_1", workspace: "/repo/app" },
    });

    options.onSuccess({ id: "project_1", name: "Alpha" });
    expect(onCreated).toHaveBeenCalledWith("Alpha");
  });

  it("does not allow creating a Project without an online host and folder", () => {
    useHostsMock.mockReturnValue({ data: [] });
    renderButton();
    fireEvent.click(screen.getByTestId("new-project"));
    fireEvent.change(screen.getByPlaceholderText("Project name…"), {
      target: { value: "Alpha" },
    });

    expect(
      screen.getByText("Connect an online host before creating a project"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("new-project-confirm")).toBeDisabled();
  });
});
