import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getRunEvaluation,
  getRunInspector,
  parseRunEvaluationResponse,
  parseRunInspectorResponse,
} from "@/lib/runsApi";
import { runEvaluationFixture, runInspectorFixture } from "@/lib/runsApi.fixture";
import { useRun, useRunEvaluation } from "./useRuns";

vi.mock("@/lib/runsApi", async (importOriginal) => {
  const original = await importOriginal<Record<string, unknown>>();
  return {
    ...original,
    getRunEvaluation: vi.fn(),
    getRunInspector: vi.fn(),
    refreshRunEvaluation: vi.fn(),
  };
});

const getInspectorMock = vi.mocked(getRunInspector);
const getEvaluationMock = vi.mocked(getRunEvaluation);
let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
});

afterEach(() => queryClient.clear());

describe("Run query lifecycle", () => {
  it("refetches evaluation once when a Run transitions into a terminal state", async () => {
    const inspector = parseRunInspectorResponse(runInspectorFixture);
    const evaluation = parseRunEvaluationResponse(runEvaluationFixture);
    getInspectorMock
      .mockResolvedValueOnce({ ...inspector, run: { ...inspector.run, status: "running" } })
      .mockResolvedValueOnce({ ...inspector, run: { ...inspector.run, status: "completed" } });
    getEvaluationMock
      .mockResolvedValueOnce({ ...evaluation, status: "preview" })
      .mockResolvedValueOnce({ ...evaluation, status: "final" });

    const { result } = renderHook(
      () => ({
        run: useRun("run-1"),
        evaluation: useRunEvaluation("run-1"),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.run.data?.run.status).toBe("running"));
    await waitFor(() => expect(result.current.evaluation.data?.status).toBe("preview"));

    await act(async () => {
      await result.current.run.refetch();
    });

    await waitFor(() => expect(result.current.run.data?.run.status).toBe("completed"));
    await waitFor(() => expect(getEvaluationMock).toHaveBeenCalledTimes(2));
    expect(result.current.evaluation.data?.status).toBe("final");
  });
});
