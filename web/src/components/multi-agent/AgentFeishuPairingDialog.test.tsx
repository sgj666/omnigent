import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import { AgentFeishuPairingDialog } from "./AgentFeishuPairingDialog";

const mocks = vi.hoisted(() => ({
  connection: { data: null as Record<string, unknown> | null, isLoading: false, error: null },
  surface: { data: undefined as Record<string, unknown> | undefined, error: null },
  begin: { mutateAsync: vi.fn(), isPending: false, error: null },
  disconnect: { mutateAsync: vi.fn(), isPending: false, error: null },
  bind: { mutateAsync: vi.fn(), isPending: false, error: null },
  reinitialize: { mutateAsync: vi.fn(), isPending: false, error: null },
}));

vi.mock("@/hooks/useFeishuInstall", () => ({
  useAgentFeishuConnection: () => mocks.connection,
  useAgentFeishuSurface: () => mocks.surface,
  useBeginAgentFeishu: () => mocks.begin,
  useDisconnectAgentFeishu: () => mocks.disconnect,
  useBindAgentFeishuWorkspace: () => mocks.bind,
  useReinitializeAgentFeishuSurface: () => mocks.reinitialize,
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
    mocks.surface.data = undefined;
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

  it("shows connected tenant, bot, workspace repositories, and persistent actions", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
      tenant_name: "Acme tenant",
      bot_name: "Polly bot",
      binding: { installation_id: "installation-1", chat_id: "chat-1", workspace_id: "ws-1" },
    };
    mocks.surface.data = { status: "ready", surface_type: "menu" };
    renderDialog();

    expect(screen.getByText("Acme tenant")).toBeVisible();
    expect(screen.getByText("Polly bot")).toBeVisible();
    expect(screen.getByText("1 repositories: api")).toBeVisible();
    expect(screen.getByText("Switch workspace")).toBeVisible();
    expect(screen.getByText("Approve necessary approval")).toBeVisible();
    expect(screen.getByText("Logs / failure reason")).toBeVisible();
  });

  it("retries partial surface provisioning and switches the bound workspace", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
      binding: {
        installation_id: "installation-1",
        chat_id: "chat-1",
        workspace_id: "ws-1",
        execution_mode: "auto",
      },
    };
    mocks.surface.data = {
      status: "partial",
      surface_type: "persistent_card",
      error: "menu provisioning failed; using persistent card",
    };
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Retry provisioning" }));
    fireEvent.change(screen.getByLabelText("Default workspace"), {
      target: { value: "ws-2" },
    });

    expect(mocks.reinitialize.mutateAsync).toHaveBeenCalledWith("agent-1");
    expect(mocks.bind.mutateAsync).toHaveBeenCalledWith({
      agentId: "agent-1",
      input: {
        installation_id: "installation-1",
        chat_id: "chat-1",
        workspace_id: "ws-2",
        execution_mode: "auto",
      },
    });
    expect(screen.getByText("2 repositories: web, docs")).toBeVisible();
  });

  it("shows a failed surface reason and offers the same idempotent retry", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
    };
    mocks.surface.data = {
      status: "failed",
      surface_type: "none",
      error: "surface provisioning failed",
    };
    renderDialog();

    expect(screen.getByRole("alert")).toHaveTextContent("surface provisioning failed");
    fireEvent.click(screen.getByRole("button", { name: "Retry provisioning" }));

    expect(mocks.reinitialize.mutateAsync).toHaveBeenCalledWith("agent-1");
  });

  it("replaces an expired grant with a new QR flow", () => {
    mocks.connection.data = {
      id: "installation-1",
      agent_id: "agent-1",
      status: "expired",
    };
    renderDialog();

    expect(screen.getByRole("alert")).toHaveTextContent("expired");
    fireEvent.click(screen.getByRole("button", { name: "Create a new QR code" }));

    expect(mocks.begin.mutateAsync).toHaveBeenCalledWith("agent-1");
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
