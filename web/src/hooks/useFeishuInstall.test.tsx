import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { beginFeishuInstall, pollFeishuInstall, type FeishuInstallSession } from "@/lib/feishuApi";
import { useFeishuInstall, useFeishuInstallStatus } from "./useFeishuInstall";

vi.mock("@/lib/feishuApi", () => ({
  beginFeishuInstall: vi.fn(),
  pollFeishuInstall: vi.fn(),
}));

const pollMock = vi.mocked(pollFeishuInstall);
const beginMock = vi.mocked(beginFeishuInstall);

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
});
