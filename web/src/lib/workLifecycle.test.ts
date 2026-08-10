import { describe, expect, it } from "vitest";
import { parseInboxItemProjection, parseTaskLifecycleEvent } from "./workLifecycle";

function eventPayload(): Record<string, unknown> {
  return {
    event_id: "evt_1",
    idempotency_key: "run_1:succeeded:1",
    type: "run.succeeded",
    occurred_at: "2026-08-06T12:30:00Z",
    task_id: "task_1",
    run_id: "run_1",
    session_id: "conv_1",
    source: { kind: "runtime", id: "runner_1" },
    summary: "Research completed",
    task_state: "done",
    run_state: "succeeded",
    result: { summary: "Three findings", artifact_ids: ["artifact_1"] },
  };
}

describe("Task lifecycle contract", () => {
  it("parses a normalized event and applies collection defaults", () => {
    const event = parseTaskLifecycleEvent(eventPayload());
    expect(event.type).toBe("run.succeeded");
    expect(event.result?.artifact_ids).toEqual(["artifact_1"]);
    expect(event.metadata).toEqual({});
  });

  it.each([
    ["unknown run state", { run_state: "complete" }],
    ["unknown type", { type: "run.finished" }],
    ["naive timestamp", { occurred_at: "2026-08-06T12:30:00" }],
    ["missing run id", { run_id: undefined }],
  ])("rejects %s", (_name, change) => {
    expect(() => parseTaskLifecycleEvent({ ...eventPayload(), ...change })).toThrow();
  });

  it("requires structured failure details for failed runs", () => {
    expect(() =>
      parseTaskLifecycleEvent({
        ...eventPayload(),
        type: "run.failed",
        run_state: "failed",
        result: undefined,
      }),
    ).toThrow(/failure details/);
  });
});

describe("Inbox projection contract", () => {
  it("requires explicit unread and deduplication state", () => {
    const item = parseInboxItemProjection({
      item_id: "inbox_1",
      dedupe_key: "task_1:run_1:completed",
      source_event_id: "evt_1",
      category: "completed",
      task_id: "task_1",
      run_id: "run_1",
      title: "Task completed",
      summary: "Research completed",
      is_unread: true,
      created_at: "2026-08-06T12:30:00Z",
    });
    expect(item.is_unread).toBe(true);
    expect(item.dedupe_key).toBe("task_1:run_1:completed");

    expect(() =>
      parseInboxItemProjection({
        item_id: "inbox_2",
        source_event_id: "evt_2",
        category: "progress",
        task_id: "task_1",
        title: "Progress",
        summary: "Halfway",
        created_at: "2026-08-06T12:30:00Z",
      }),
    ).toThrow();
  });
});
