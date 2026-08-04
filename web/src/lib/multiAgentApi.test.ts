import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authenticatedFetch } from "./identity";
import {
  AgentVersionConflict,
  cloneAgentBundle,
  createAgentBundle,
  deleteAgentBundle,
  exportAgentBundle,
  getAgentBundle,
  getAgentFormSchema,
  importAgentBundle,
  listMultiAgents,
  startMultiAgentRun,
  updateAgentBundle,
  validateAgentBundleArchive,
  type AgentBundleDraft,
  type AgentBundleUpdateRequest,
} from "./multiAgentApi";

vi.mock("./identity", () => ({ authenticatedFetch: vi.fn() }));

const fetchMock = vi.mocked(authenticatedFetch);

const summary = {
  id: "ag_polly",
  name: "polly",
  description: "Coordinator with two workers",
  harness: "claude-sdk",
  model_source: "bundle",
  worker_count: 2,
  skill_count: 1,
  mcp_count: 0,
  version: 3,
  updated_at: 1_786_000_000,
  builtin: true,
  editable: false,
  validation_status: "valid" as const,
  feishu_status: "disconnected" as const,
  recent_run: null,
};

const draft: AgentBundleDraft = {
  agent: { ...summary, id: "ag_custom", name: "my-polly", builtin: false, editable: true },
  version: 3,
  digest: "sha256:abc",
  files: [
    {
      path: "config.yaml",
      content: "name: my-polly\n",
      encoding: "utf-8",
      media_type: "application/yaml",
      data: { name: "my-polly" },
    },
  ],
  coordinator: {
    path: "config.yaml",
    content: "name: my-polly\n",
    encoding: "utf-8",
    media_type: "application/yaml",
    data: { name: "my-polly" },
  },
  workers: [],
  diagnostics: [],
  schema_version: "1",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("multi-agent bundle API", () => {
  it("starts a provider-neutral run through Core RunService", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          id: "run_1",
          status: "queued",
          agent_id: "ag_custom",
          workspace_id: "ws_1",
        },
        201,
      ),
    );

    await startMultiAgentRun({
      agent_id: "ag_custom",
      workspace_id: "ws_1",
      host_id: "host_1",
    });

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_id: "ag_custom",
        workspace_id: "ws_1",
        host_id: "host_1",
      }),
    });
  });

  it("keeps catalog summaries separate from full bundle drafts", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ object: "list", data: [summary] }))
      .mockResolvedValueOnce(jsonResponse(draft));

    await expect(listMultiAgents()).resolves.toEqual([summary]);
    await expect(getAgentBundle("ag custom")).resolves.toEqual(draft);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/v1/agents");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/v1/agents/ag%20custom/bundle");
  });

  it("loads every page of the agent catalog", async () => {
    const second = { ...summary, id: "ag_custom", name: "custom", builtin: false, editable: true };
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [summary], has_more: true, last_id: "ag_polly" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [second], has_more: false, last_id: "ag_custom" }),
      );

    await expect(listMultiAgents()).resolves.toEqual([summary, second]);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/v1/agents");
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/v1/agents?after=ag_polly");
  });

  it("reuses the same abort signal for every catalog page", async () => {
    const controller = new AbortController();
    const second = { ...summary, id: "ag_custom", name: "custom", builtin: false, editable: true };
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [summary], has_more: true, last_id: "cursor-1" }),
      )
      .mockResolvedValueOnce(jsonResponse({ object: "list", data: [second], has_more: false }));

    await expect(listMultiAgents(controller.signal)).resolves.toEqual([summary, second]);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/v1/agents", { signal: controller.signal });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/v1/agents?after=cursor-1", {
      signal: controller.signal,
    });
  });

  it("stops pagination and preserves AbortError when the catalog request is aborted", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("The operation was aborted.", "AbortError");
    fetchMock.mockImplementationOnce((_url, init) => {
      const signal = init?.signal;
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(abortError), { once: true });
      });
    });

    const pending = listMultiAgents(controller.signal);
    controller.abort();

    await expect(pending).rejects.toBe(abortError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not fetch another page when the signal is aborted while parsing a page", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("The operation was aborted.", "AbortError");
    fetchMock.mockImplementationOnce(async () => {
      controller.abort(abortError);
      return jsonResponse({
        object: "list",
        data: [summary],
        has_more: true,
        last_id: "cursor-1",
      });
    });

    await expect(listMultiAgents(controller.signal)).rejects.toBe(abortError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stops when a paginated response repeats a cursor", async () => {
    const second = { ...summary, id: "ag_custom", name: "custom", builtin: false, editable: true };
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [summary], has_more: true, last_id: "cursor-1" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [second], has_more: true, last_id: "cursor-1" }),
      );

    await expect(listMultiAgents()).resolves.toEqual([summary, second]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops on an empty page even when has_more is true", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ object: "list", data: [], has_more: true, last_id: "cursor-1" }),
    );

    await expect(listMultiAgents()).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("stops safely when has_more has no cursor", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ object: "list", data: [summary], has_more: true }),
    );

    await expect(listMultiAgents()).resolves.toEqual([summary]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("deduplicates repeated agent ids without changing first-seen order", async () => {
    const second = { ...summary, id: "ag_second", name: "second" };
    const duplicate = { ...summary, name: "later duplicate" };
    const third = { ...summary, id: "ag_third", name: "third" };
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          object: "list",
          data: [summary, second],
          has_more: true,
          last_id: "cursor-1",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ object: "list", data: [duplicate, third], has_more: false }),
      );

    await expect(listMultiAgents()).resolves.toEqual([summary, second, third]);
  });

  it("loads the versioned agent form schema", async () => {
    const schema = {
      schema_version: "1",
      fields: [
        {
          path: "/executor/model",
          type: "string",
          group: "model",
          required: false,
          secret: false,
          translation_key: "multiAgent.fields.model",
        },
      ],
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(schema));

    await expect(getAgentFormSchema()).resolves.toEqual(schema);
    expect(fetchMock).toHaveBeenCalledWith("/v1/agent-spec/schema");
  });

  it("passes abort signals to bundle and schema GET requests", async () => {
    const controller = new AbortController();
    const schema = { schema_version: "1", fields: [] };
    fetchMock
      .mockResolvedValueOnce(jsonResponse(draft))
      .mockResolvedValueOnce(jsonResponse(schema));

    await expect(getAgentBundle("ag custom", controller.signal)).resolves.toEqual(draft);
    await expect(getAgentFormSchema(controller.signal)).resolves.toEqual(schema);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/v1/agents/ag%20custom/bundle", {
      signal: controller.signal,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/v1/agent-spec/schema", {
      signal: controller.signal,
    });
  });

  it("validates a gzip bundle without persisting it", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        valid: false,
        diagnostics: [
          {
            severity: "error",
            code: "invalid_yaml",
            file: "config.yaml",
            path: "/executor",
            line: 4,
            column: 2,
            agent: "coordinator",
            message: "bad yaml",
            summary_key: "multiAgent.diagnostics.invalidYaml",
          },
        ],
      }),
    );
    const bundle = new Blob(["gzip"], { type: "application/gzip" });

    const result = await validateAgentBundleArchive(bundle);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/agents/validate");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("bundle")).toBeInstanceOf(Blob);
    expect(result.diagnostics[0]).toMatchObject({
      code: "invalid_yaml",
      file: "config.yaml",
      path: "/executor",
      line: 4,
      column: 2,
    });
  });

  it("creates a server-generated minimal bundle from a typed shape", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(draft, 201));

    await createAgentBundle({
      name: "my-polly",
      description: "A new team",
      shape: "multi-agent",
    });

    expect(fetchMock).toHaveBeenCalledWith("/v1/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "my-polly",
        description: "A new team",
        shape: "multi-agent",
      }),
    });
  });

  it("imports a gzip bundle as multipart data", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(draft, 201));
    const bundle = new Blob(["gzip"], { type: "application/gzip" });

    await importAgentBundle(bundle);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/agents/import");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
    expect((init.body as FormData).get("bundle")).toBeInstanceOf(Blob);
  });

  it("updates patches and atomic worker operations through one versioned PUT", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...draft, version: 4 }));
    const request: AgentBundleUpdateRequest = {
      expected_version: 3,
      patches: [
        { file: "config.yaml", op: "replace", path: "/description", value: "Updated" },
        { file: "AGENTS.md", op: "replace_file", value: "New instructions" },
      ],
      worker_operations: [
        { op: "add", name: "reviewer", source: "coordinator" },
        { op: "copy", source: "reviewer", target: "reviewer-2" },
        { op: "rename", source: "reviewer-2", target: "critic" },
        { op: "delete", name: "critic", confirmed_references: ["/tools/agents/2"] },
      ],
    };

    await updateAgentBundle("ag/custom", request);

    expect(fetchMock).toHaveBeenCalledWith("/v1/agents/ag%2Fcustom", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
  });

  it("retains the server version on an optimistic update conflict", async () => {
    const text = vi.fn().mockResolvedValue(
      JSON.stringify({
        error: { code: "conflict", message: "Agent bundle changed" },
        expected_version: 3,
        server_version: 5,
        diagnostics: [
          {
            severity: "error",
            code: "version_conflict",
            file: null,
            path: null,
            line: null,
            column: null,
            message: "Reload before saving",
          },
        ],
      }),
    );
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: "Conflict",
      text,
    } as unknown as Response);

    const error = await updateAgentBundle("ag_custom", {
      expected_version: 3,
      patches: [],
    }).catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(AgentVersionConflict);
    expect(error).toMatchObject({
      status: 409,
      expected_version: 3,
      server_version: 5,
      message: "Agent bundle changed",
      diagnostics: [{ code: "version_conflict", message: "Reload before saving" }],
    });
    expect(text).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["plain text", "  upstream unavailable\n", "upstream unavailable"],
    ["HTML", "\n<html><body>Bad Gateway</body></html>  ", "<html><body>Bad Gateway</body></html>"],
  ])("retains a trimmed %s error body", async (_kind, body, message) => {
    fetchMock.mockResolvedValueOnce(new Response(body, { status: 502, statusText: "Bad Gateway" }));

    await expect(getAgentBundle("ag_custom")).rejects.toThrow(message);
  });

  it("clones a built-in bundle without using the create endpoint", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(draft, 201));

    await cloneAgentBundle("ag_polly", { name: "my-polly", description: "Custom clone" });

    expect(fetchMock).toHaveBeenCalledWith("/v1/agents/ag_polly/clone", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "my-polly", description: "Custom clone" }),
    });
  });

  it("deletes editable bundles", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await deleteAgentBundle("ag custom");

    expect(fetchMock).toHaveBeenCalledWith("/v1/agents/ag%20custom", { method: "DELETE" });
  });

  it("exports the exact binary gzip response", async () => {
    const bytes = new Uint8Array([0x1f, 0x8b, 0x08, 0x00]);
    fetchMock.mockResolvedValueOnce(
      new Response(bytes, { headers: { "Content-Type": "application/gzip" } }),
    );

    const result = await exportAgentBundle("ag_polly");

    expect(fetchMock).toHaveBeenCalledWith("/v1/agents/ag_polly/export");
    expect(result.type).toBe("application/gzip");
    expect(new Uint8Array(await result.arrayBuffer())).toEqual(bytes);
  });
});
