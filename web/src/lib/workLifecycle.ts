import { z } from "zod";

export const TASK_STATES = [
  "backlog",
  "todo",
  "in_progress",
  "review",
  "done",
  "cancelled",
] as const;

export const TASK_RUN_STATES = [
  "queued",
  "running",
  "waiting",
  "succeeded",
  "failed",
  "cancelled",
] as const;

export const TASK_LIFECYCLE_EVENT_TYPES = [
  "task.created",
  "task.updated",
  "task.completed",
  "task.cancelled",
  "run.queued",
  "run.started",
  "run.progress",
  "run.waiting",
  "run.succeeded",
  "run.failed",
  "run.cancelled",
] as const;

export const INBOX_CATEGORIES = ["action_required", "progress", "completed", "failed"] as const;

const nonEmptyId = z.string().min(1).max(256);
const awareIsoTimestamp = z
  .string()
  .refine(
    (value) => /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && !Number.isNaN(Date.parse(value)),
    "Expected an ISO 8601 timestamp with timezone",
  );

export const lifecycleEventSourceSchema = z
  .object({
    kind: z.string().min(1).max(64),
    id: nonEmptyId.optional(),
    display_name: nonEmptyId.optional(),
  })
  .strict();

export const requiredActionSchema = z
  .object({
    action_id: nonEmptyId,
    kind: z.string().min(1).max(64),
    prompt: z.string().min(1).max(4000),
    expires_at: awareIsoTimestamp.optional(),
  })
  .strict();

export const failureDetailsSchema = z
  .object({
    code: z.string().min(1).max(128),
    message: z.string().min(1).max(4000),
    retryable: z.boolean().default(false),
  })
  .strict();

export const resultDetailsSchema = z
  .object({
    summary: z.string().max(4000).optional(),
    artifact_ids: z.array(z.string().min(1)).default([]),
  })
  .strict();

export const taskLifecycleEventSchema = z
  .object({
    event_id: nonEmptyId,
    idempotency_key: z.string().min(1).max(512),
    type: z.enum(TASK_LIFECYCLE_EVENT_TYPES),
    occurred_at: awareIsoTimestamp,
    task_id: nonEmptyId,
    run_id: nonEmptyId.optional(),
    session_id: nonEmptyId.optional(),
    project_id: nonEmptyId.optional(),
    source: lifecycleEventSourceSchema,
    summary: z.string().min(1).max(1000),
    task_state: z.enum(TASK_STATES).optional(),
    run_state: z.enum(TASK_RUN_STATES).optional(),
    action: requiredActionSchema.optional(),
    failure: failureDetailsSchema.optional(),
    result: resultDetailsSchema.optional(),
    metadata: z.record(z.string(), z.unknown()).default({}),
  })
  .strict()
  .superRefine((event, context) => {
    if (event.type.startsWith("run.") && event.run_id === undefined) {
      context.addIssue({ code: "custom", path: ["run_id"], message: "Run events require run_id" });
    }
    if (event.type === "run.failed" && event.failure === undefined) {
      context.addIssue({
        code: "custom",
        path: ["failure"],
        message: "run.failed events require failure details",
      });
    }
  });

export const inboxItemProjectionSchema = z
  .object({
    item_id: nonEmptyId,
    dedupe_key: z.string().min(1).max(512),
    source_event_id: nonEmptyId,
    category: z.enum(INBOX_CATEGORIES),
    task_id: nonEmptyId,
    run_id: nonEmptyId.optional(),
    session_id: nonEmptyId.optional(),
    project_id: nonEmptyId.optional(),
    title: z.string().min(1).max(256),
    summary: z.string().min(1).max(1000),
    action: requiredActionSchema.optional(),
    is_unread: z.boolean(),
    created_at: awareIsoTimestamp,
  })
  .strict();

export type TaskState = (typeof TASK_STATES)[number];
export type TaskRunState = (typeof TASK_RUN_STATES)[number];
export type TaskLifecycleEvent = z.infer<typeof taskLifecycleEventSchema>;
export type InboxItemProjection = z.infer<typeof inboxItemProjectionSchema>;

export function parseTaskLifecycleEvent(input: unknown): TaskLifecycleEvent {
  return taskLifecycleEventSchema.parse(input);
}

export function parseInboxItemProjection(input: unknown): InboxItemProjection {
  return inboxItemProjectionSchema.parse(input);
}
