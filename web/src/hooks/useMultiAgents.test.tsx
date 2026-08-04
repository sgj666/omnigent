import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cloneAgentBundle,
  createAgentBundle,
  deleteAgentBundle,
  getAgentBundle,
  getAgentBundleOptions,
  getAgentFormSchema,
  importAgentBundle,
  listMultiAgents,
  updateAgentBundle,
  validateAgentBundleArchive,
} from "@/lib/multiAgentApi";
import {
  agentFormSchemaQueryKey,
  multiAgentQueryKey,
  multiAgentsQueryKey,
  useAgentFormSchema,
  useAgentBundleOptions,
  useCloneMultiAgent,
  useCreateMultiAgent,
  useDeleteMultiAgent,
  useImportMultiAgent,
  useMultiAgent,
  useMultiAgents,
  useUpdateMultiAgent,
  useValidateAgentBundle,
} from "./useMultiAgents";

vi.mock("@/lib/multiAgentApi", () => ({
  cloneAgentBundle: vi.fn(),
  createAgentBundle: vi.fn(),
  deleteAgentBundle: vi.fn(),
  getAgentBundle: vi.fn(),
  getAgentBundleOptions: vi.fn(),
  getAgentFormSchema: vi.fn(),
  importAgentBundle: vi.fn(),
  listMultiAgents: vi.fn(),
  updateAgentBundle: vi.fn(),
  validateAgentBundleArchive: vi.fn(),
}));

const api = {
  clone: vi.mocked(cloneAgentBundle),
  create: vi.mocked(createAgentBundle),
  delete: vi.mocked(deleteAgentBundle),
  detail: vi.mocked(getAgentBundle),
  options: vi.mocked(getAgentBundleOptions),
  schema: vi.mocked(getAgentFormSchema),
  import: vi.mocked(importAgentBundle),
  list: vi.mocked(listMultiAgents),
  update: vi.mocked(updateAgentBundle),
  validate: vi.mocked(validateAgentBundleArchive),
};

const summary = {
  id: "ag_custom",
  name: "custom",
  description: null,
  harness: "codex",
  worker_count: 0,
  skill_count: 0,
  mcp_count: 0,
  version: 1,
  digest: "sha256:abc",
  readonly: false,
  updated_at: 1_786_000_000,
  builtin: false,
  editable: true,
  validation_status: "valid" as const,
};

const draft = {
  card: summary,
  version: 1,
  digest: "sha256:abc",
  files: [],
  coordinator: null,
  workers: [],
  diagnostics: [],
  schema_version: "1",
};

const schema = { schema_version: "1", fields: [] };
const options = {
  harnesses: [{ id: "community-harness", label: "Community Harness" }],
  models: [],
  tools: [],
  skills: [],
  mcp: [],
  environment: [],
};

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
  api.list.mockResolvedValue([summary]);
  api.detail.mockResolvedValue(draft);
  api.schema.mockResolvedValue(schema);
  api.options.mockResolvedValue(options);
  api.create.mockResolvedValue(draft);
  api.import.mockResolvedValue(draft);
  api.update.mockResolvedValue({ ...draft, version: 2 });
  api.clone.mockResolvedValue(draft);
  api.delete.mockResolvedValue(undefined);
  api.validate.mockResolvedValue({ valid: true, diagnostics: [] });
});

afterEach(() => {
  queryClient.clear();
});

describe("multi-agent query hooks", () => {
  it("uses the catalog and detail query keys", async () => {
    expect(multiAgentsQueryKey).toEqual(["multi-agents"]);
    expect(multiAgentQueryKey("ag_custom")).toEqual(["multi-agents", "ag_custom"]);

    const { result } = renderHook(
      () => ({ catalog: useMultiAgents(), detail: useMultiAgent("ag_custom") }),
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.catalog.isSuccess).toBe(true);
      expect(result.current.detail.isSuccess).toBe(true);
    });
    expect(api.list).toHaveBeenCalledTimes(1);
    const listSignal = api.list.mock.calls[0][0];
    const detailSignal = api.detail.mock.calls[0][1];
    expect(listSignal).toBeInstanceOf(AbortSignal);
    expect(detailSignal).toBeInstanceOf(AbortSignal);
    expect(api.detail).toHaveBeenCalledWith("ag_custom", detailSignal);
  });

  it("does not load a draft without an agent id", async () => {
    const { result } = renderHook(() => useMultiAgent(null), { wrapper });
    await Promise.resolve();

    expect(result.current.fetchStatus).toBe("idle");
    expect(api.detail).not.toHaveBeenCalled();
  });

  it("enables the form schema query with its key and abort signal", async () => {
    expect(agentFormSchemaQueryKey).toEqual(["agent-form-schema"]);
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useAgentFormSchema(enabled),
      { initialProps: { enabled: false }, wrapper },
    );
    await Promise.resolve();

    expect(result.current.fetchStatus).toBe("idle");
    expect(api.schema).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.schema).toHaveBeenCalledTimes(1);
    expect(api.schema.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
  });

  it("loads Bundle options from the provider catalog", async () => {
    const { result } = renderHook(() => useAgentBundleOptions(true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toEqual(options);
    expect(api.options.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
  });
});

describe("multi-agent mutation hooks", () => {
  it("forwards the selected archive to validation", async () => {
    const { result } = renderHook(() => useValidateAgentBundle(), { wrapper });
    const bundle = new Blob(["gzip"], { type: "application/gzip" });

    await act(async () => {
      await result.current.mutateAsync(bundle);
    });

    expect(api.validate).toHaveBeenCalledWith(bundle);
  });

  it("invalidates catalog, created detail, and available agents after create", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCreateMultiAgent(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        name: "custom",
        config: { spec_version: 1, name: "custom" },
      });
    });

    expect(api.create).toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentsQueryKey, exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentQueryKey("ag_custom") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["available-agents"] });
  });

  it("invalidates catalog, imported detail, and available agents after import", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useImportMultiAgent(), { wrapper });
    const bundle = new Blob(["gzip"], { type: "application/gzip" });

    await act(async () => {
      await result.current.mutateAsync(bundle);
    });

    expect(api.import).toHaveBeenCalledWith(bundle);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentsQueryKey, exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentQueryKey("ag_custom") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["available-agents"] });
  });

  it("invalidates catalog, cloned detail, and available agents after clone", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCloneMultiAgent(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ agent_id: "ag_polly", input: { name: "custom" } });
    });

    expect(api.clone).toHaveBeenCalledWith("ag_polly", { name: "custom" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentsQueryKey, exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentQueryKey("ag_custom") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["available-agents"] });
  });

  it("updates with the expected version and invalidates the edited detail", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useUpdateMultiAgent(), { wrapper });
    const request = {
      expected_version: 1,
      worker_operations: [{ op: "add" as const, name: "reviewer", source: "minimal" as const }],
    };

    await act(async () => {
      await result.current.mutateAsync({ agent_id: "ag_custom", request });
    });

    expect(api.update).toHaveBeenCalledWith("ag_custom", request);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentsQueryKey, exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentQueryKey("ag_custom") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["available-agents"] });
  });

  it("invalidates the deleted detail using the mutation input", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDeleteMultiAgent(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync("ag_custom");
    });

    expect(api.delete).toHaveBeenCalledWith("ag_custom");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: multiAgentQueryKey("ag_custom") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["available-agents"] });
  });
});
