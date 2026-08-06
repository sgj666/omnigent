import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import { AgentFeishuPairingDialog } from "./AgentFeishuPairingDialog";

const mocks = vi.hoisted(() => ({
  connection: { data: null as Record<string, unknown> | null, isLoading: false, error: null },
  profile: {
    data: {
      details_enabled: true,
      details_base_url: "https://omnigent.example.com",
      actions: ["quick_commands", "manage_devices", "switch_workspace"],
    } as Record<string, unknown>,
    error: null,
  },
  begin: { mutateAsync: vi.fn(), isPending: false, error: null },
  disconnect: { mutateAsync: vi.fn(), isPending: false, error: null },
  defaultScope: { data: null as Record<string, unknown> | null, isLoading: false, error: null },
  setDefaultScope: { mutateAsync: vi.fn(), isPending: false, error: null },
  setProfile: { mutateAsync: vi.fn(), isPending: false, error: null },
}));

vi.mock("@/hooks/useFeishuInstall", () => ({
  useAgentFeishuConnection: () => mocks.connection,
  useAgentFeishuSurfaceProfile: () => mocks.profile,
  useBeginAgentFeishu: () => mocks.begin,
  useDisconnectAgentFeishu: () => mocks.disconnect,
  useAgentDefaultWorkspaceScope: () => mocks.defaultScope,
  useSetAgentDefaultWorkspaceScope: () => mocks.setDefaultScope,
  useSetAgentFeishuSurfaceProfile: () => mocks.setProfile,
}));

vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({ data: [{ host_id: "host-1", name: "Local Mac", status: "online" }] }),
}));

vi.mock("@/shell/WorkspacePicker", () => ({
  WorkspacePicker: ({ onSelect }: { onSelect: (path: string) => void }) => (
    <button type="button" onClick={() => onSelect("/Users/me/chosen")}>
      Choose folder in picker
    </button>
  ),
}));

vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({
    data: [
      { id: "ws-1", root_path: "/workspace/one", repositories: [{ name: "api", path: "/api" }] },
      {
        id: "ws-2",
        root_path: "/workspace/two",
        repositories: [
          { name: "web", path: "/web" },
          { name: "docs", path: "/docs" },
        ],
      },
    ],
  }),
}));

function renderDialog(onStatusChange = vi.fn()) {
  return render(
    <AgentFeishuPairingDialog
      agentId="agent-1"
      agentName="Polly"
      open
      onOpenChange={vi.fn()}
      onStatusChange={onStatusChange}
    />,
  );
}

describe("AgentFeishuPairingDialog", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    mocks.connection.data = null;
    mocks.profile.data = {
      details_enabled: true,
      details_base_url: "https://omnigent.example.com",
      actions: ["quick_commands", "manage_devices", "switch_workspace"],
    };
    mocks.setProfile.mutateAsync.mockResolvedValue(mocks.profile.data);
    mocks.setDefaultScope.mutateAsync.mockResolvedValue(mocks.defaultScope.data);
    mocks.defaultScope.data = null;
    await i18n.changeLanguage("en");
  });

  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("keeps a pending QR, code, and expiry visible when the UI language changes", async () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "pending",
      session: "grant-1",
      verification_uri_complete: "https://open.feishu.test/verify?user_code=PAIR-123",
      expires_in: 300,
    };
    renderDialog();

    expect(screen.getByRole("img", { name: "Feishu pairing QR code" })).toBeVisible();
    expect(screen.getByText("PAIR-123")).toBeVisible();
    expect(screen.getByText(/Expires in \d+s/)).toBeVisible();

    await act(() => i18n.changeLanguage("zh-CN"));

    expect(screen.getByRole("img", { name: "飞书配对二维码" })).toBeVisible();
    expect(screen.getByText("PAIR-123")).toBeVisible();
  });

  it("separates Agent capabilities from the manually published floating menu", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
      expires_in: 0,
      tenant_name: "Acme tenant",
      bot_name: "Polly bot",
      binding: { installation_id: "installation-1", chat_id: "chat-1", workspace_id: "ws-1" },
    };
    renderDialog();

    expect(screen.getByText("Acme tenant")).toBeVisible();
    expect(screen.getByText("Polly bot")).toBeVisible();
    expect(screen.getByText("Execution details")).toBeVisible();
    expect(screen.getByText("Always on")).toBeVisible();
    expect(screen.getByText("Agent Feishu capabilities")).toBeVisible();
    expect(screen.getByText("Feishu floating menu")).toBeVisible();
    expect(screen.getByText("application.bot.menu_v6")).toBeVisible();
    expect(screen.getByText("manage_devices")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open Feishu developer console" })).toHaveAttribute(
      "href",
      "https://open.feishu.cn/app",
    );
    expect(screen.getByRole("checkbox", { name: /Quick commands/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Manage devices/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Workspace/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Current task/ })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Create a new QR code" })).not.toBeInTheDocument();
  });

  it("shows the Feishu permission action when the details tab cannot be synced", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
    };
    mocks.defaultScope.data = { workspace: "/Users/me/projects", host_id: "host-1" };
    mocks.profile.data = {
      details_enabled: true,
      details_base_url: "https://omnigent.example.com",
      actions: ["quick_commands"],
      sync: {
        status: "permission_required",
        message: "Grant chat tab permissions.",
        permission_url: "https://open.feishu.cn/app/cli_test/auth",
      },
    };

    renderDialog();

    expect(screen.getByText("Execution details needs Feishu permission")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open Feishu permissions" })).toHaveAttribute(
      "href",
      "https://open.feishu.cn/app/cli_test/auth",
    );
  });

  it("saves the directory and selected entries without reconnecting", async () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
    };
    renderDialog();

    fireEvent.change(screen.getByLabelText("Default start directory"), {
      target: { value: "/Users/me/projects" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Current task/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save Feishu configuration" }));

    await waitFor(() => {
      expect(mocks.setDefaultScope.mutateAsync).toHaveBeenCalledWith({
        agentId: "agent-1",
        input: { host_id: "host-1", workspace: "/Users/me/projects" },
      });
      expect(mocks.setProfile.mutateAsync).toHaveBeenCalledWith({
        agentId: "agent-1",
        input: {
          details_base_url: "https://omnigent.example.com",
          actions: ["quick_commands", "manage_devices", "switch_workspace", "current_run"],
        },
      });
    });
    expect(mocks.begin.mutateAsync).not.toHaveBeenCalled();
  });

  it("lets the operator choose the working directory from the selected host", () => {
    mocks.connection.data = { id: "installation-1", agent_id: "agent-1", status: "connected" };
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Browse directories" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose folder in picker" }));

    expect(screen.getByLabelText("Default start directory")).toHaveValue("/Users/me/chosen");
  });

  it("replaces an expired grant after saving the current configuration", async () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "expired",
    };
    mocks.defaultScope.data = { workspace: "/Users/me/projects", host_id: "host-1" };
    renderDialog();

    expect(screen.getByRole("alert")).toHaveTextContent("expired");
    fireEvent.click(screen.getByRole("button", { name: "Create a new QR code" }));

    await waitFor(() => expect(mocks.begin.mutateAsync).toHaveBeenCalledWith("agent-1"));
  });

  it("disconnects the current Agent-scoped installation", async () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
    };
    const onStatusChange = vi.fn();
    renderDialog(onStatusChange);

    fireEvent.click(screen.getByRole("button", { name: "Disconnect Feishu" }));

    expect(mocks.disconnect.mutateAsync).toHaveBeenCalledWith("agent-1");
    await waitFor(() => expect(onStatusChange).toHaveBeenCalledWith("disconnected"));
  });
});
