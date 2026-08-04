import { beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import * as feishuApi from "./feishuApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

const fetchMock = vi.mocked(authenticatedFetch);
const response = (body: unknown, status = 200) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("Agent-scoped Feishu API", () => {
  beforeEach(() => fetchMock.mockReset());

  it("maps installation, polling, binding, surface, and disconnect endpoints", async () => {
    const api = feishuApi as typeof feishuApi &
      Record<string, (...args: never[]) => Promise<unknown>>;
    for (const name of [
      "beginAgentFeishuInstall",
      "pollAgentFeishuInstall",
      "getAgentFeishuInstallation",
      "disconnectAgentFeishu",
      "bindAgentFeishuWorkspace",
      "getAgentFeishuSurface",
      "reinitializeAgentFeishuSurface",
    ]) {
      expect(api[name], name).toBeTypeOf("function");
    }
    if (!api.beginAgentFeishuInstall) return;

    fetchMock
      .mockResolvedValueOnce(
        response({ id: "install-1", session: "grant-1", status: "pending" }, 201),
      )
      .mockResolvedValueOnce(response({ id: "install-1", status: "connected" }))
      .mockResolvedValueOnce(response({ id: "install-1", status: "connected" }))
      .mockResolvedValueOnce(response(undefined, 204))
      .mockResolvedValueOnce(response({ id: "binding-1", workspace_id: "ws-1" }))
      .mockResolvedValueOnce(response({ status: "partial" }))
      .mockResolvedValueOnce(response({ status: "ready" }));

    await api.beginAgentFeishuInstall("agent 1");
    await api.pollAgentFeishuInstall("agent 1", "grant 1");
    await api.getAgentFeishuInstallation("agent 1");
    await api.disconnectAgentFeishu("agent 1");
    await api.bindAgentFeishuWorkspace("agent 1", {
      installation_id: "install-1",
      chat_id: "chat-1",
      workspace_id: "ws-1",
      execution_mode: "auto",
    });
    await api.getAgentFeishuSurface("agent 1");
    await api.reinitializeAgentFeishuSurface("agent 1");

    expect(fetchMock.mock.calls).toEqual([
      ["/v1/agents/agent%201/feishu/installations", { method: "POST" }],
      ["/v1/agents/agent%201/feishu/installations/grant%201"],
      ["/v1/agents/agent%201/feishu"],
      ["/v1/agents/agent%201/feishu", { method: "DELETE" }],
      [
        "/v1/agents/agent%201/feishu/binding",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            installation_id: "install-1",
            chat_id: "chat-1",
            workspace_id: "ws-1",
            execution_mode: "auto",
          }),
        },
      ],
      ["/v1/agents/agent%201/feishu/surface/status"],
      ["/v1/agents/agent%201/feishu/surface/reinitialize", { method: "POST" }],
    ]);
  });
});
