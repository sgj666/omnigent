import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  beginFeishuInstall,
  getAgentFeishuInstallation,
  pollAgentFeishuInstall,
  pollFeishuInstall,
  type FeishuInstallSession,
} from "@/lib/feishuApi";
import {
  useAgentFeishuConnection,
  useFeishuInstall,
  useFeishuInstallStatus,
} from "./useFeishuInstall";

vi.mock("@/lib/feishuApi", () => ({
  beginFeishuInstall: vi.fn(),
  pollFeishuInstall: vi.fn(),
  getAgentFeishuInstallation: vi.fn(),
  pollAgentFeishuInstall: vi.fn(),
  beginAgentFeishuInstall: vi.fn(),
  disconnectAgentFeishu: vi.fn(),
  bindAgentFeishuWorkspace: vi.fn(),
  getAgentFeishuSurface: vi.fn(),
  reinitializeAgentFeishuSurface: vi.fn(),
}));

const pollMock = vi.mocked(pollFeishuInstall);
const beginMock = vi.mocked(beginFeishuInstall);
const getAgentMock = vi.mocked(getAgentFeishuInstallation);
const pollAgentMock = vi.mocked(pollAgentFeishuInstall);

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client: queryClient }, children);
}

describe("useFeishuInstallStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    beginMock.mockResolvedValue({
      session: "device-code-1",
      status: "pending",
      interval: 5,
    });
    pollMock.mockResolvedValue({
      session: "device-code-1",
      status: "pending",
      interval: 5,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("honors Feishu's advertised polling interval", async () => {
    renderHook(
      () =>
        useFeishuInstallStatus({
          session: "device-code-1",
          status: "pending",
          interval: 5,
        }),
      { wrapper },
    );

    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(pollMock).not.toHaveBeenCalled();

    await act(async () => void (await vi.advanceTimersByTimeAsync(2_000)));
    expect(pollMock).not.toHaveBeenCalled();

    await act(async () => void (await vi.advanceTimersByTimeAsync(3_000)));
    expect(pollMock).toHaveBeenCalledTimes(1);
  });

  it("does not invalidate a newly cached begin session and poll immediately", async () => {
    function useInstallationFlow() {
      const [session, setSession] = useState<FeishuInstallSession | null>(null);
      const begin = useFeishuInstall();
      useFeishuInstallStatus(session, session?.status === "pending");
      return {
        connect: async () => setSession(await begin.mutateAsync()),
      };
    }
    const { result } = renderHook(useInstallationFlow, { wrapper });

    await act(async () => void (await result.current.connect()));
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(pollMock).not.toHaveBeenCalled();

    await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));
    expect(pollMock).toHaveBeenCalledTimes(1);
  });

  it("uses a slower interval returned by a pending poll", async () => {
    pollMock.mockResolvedValue({
      session: "device-code-1",
      status: "pending",
      interval: 10,
    });
    renderHook(
      () =>
        useFeishuInstallStatus({
          session: "device-code-1",
          status: "pending",
          interval: 5,
        }),
      { wrapper },
    );

    await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));
    expect(pollMock).toHaveBeenCalledTimes(1);

    await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));
    expect(pollMock).toHaveBeenCalledTimes(1);

    await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));
    expect(pollMock).toHaveBeenCalledTimes(2);
  });

  it("keeps the verification URL while a pending installation is polled", async () => {
    pollMock.mockResolvedValue({
      session: "device-code-1",
      status: "pending",
      interval: 5,
      polled: true,
    });
    const { result } = renderHook(
      () =>
        useFeishuInstallStatus({
          session: "device-code-1",
          status: "pending",
          interval: 5,
          verification_uri_complete: "https://open.feishu.cn/page/launcher?user_code=TEST",
        }),
      { wrapper },
    );

    await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));
    await act(async () => void (await vi.advanceTimersByTimeAsync(1)));

    expect(result.current.data?.polled).toBe(true);
    expect(result.current.data?.verification_uri_complete).toBe(
      "https://open.feishu.cn/page/launcher?user_code=TEST",
    );
  });

  it("polls a pending Agent grant to connected without losing the Agent scope", async () => {
    getAgentMock.mockResolvedValue({
      id: "installation-1",
      agent_id: "agent-1",
      session: "grant-1",
      status: "pending",
      verification_uri_complete: "https://open.feishu.test/PAIR",
    });
    pollAgentMock.mockResolvedValue({
      id: "installation-1",
      agent_id: "agent-1",
      status: "connected",
      bot_open_id: "bot-1",
    });
    const { result } = renderHook(() => useAgentFeishuConnection("agent-1"), { wrapper });

    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(result.current.data?.status).toBe("pending");
    await act(async () => {
      await result.current.refetch();
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(pollAgentMock).toHaveBeenCalledWith("agent-1", "grant-1");
    expect(result.current.data?.status).toBe("connected");
  });
});
