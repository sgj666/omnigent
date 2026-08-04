import { throwApiError } from "./apiError";
import { authenticatedFetch } from "./identity";

export type RunExecutionMode = "auto" | "cautious" | "read_only";

export interface CreateRunInput {
  agent_id: string;
  workspace_id?: string | null;
  input: string;
  source: string;
  source_event_id: string;
  host_id?: string | null;
  execution_mode: RunExecutionMode;
}

export interface RunInspectorRunDto {
  id: string;
  actor_id: string;
  auth_scope: string;
  source: string;
  source_event_id: string;
  agent_id: string;
  bundle_version: number;
  bundle_digest: string;
  bundle_location: string;
  workspace_id: string;
  root_session_id: string | null;
  status: string;
  created_at: number;
  updated_at: number | null;
}

export interface RunDto extends RunInspectorRunDto {
  object: "run";
}

export interface RunListDto {
  object: "list";
  data: RunDto[];
}

export interface RunInspectorAgentSnapshotDto {
  id: string;
  bundle_version: number;
  bundle_digest: string;
  bundle_location: string;
}

export interface RunInspectorWorkspaceRepositoryDto {
  id: string;
  name: string;
  path: string;
}

export interface RunInspectorWorkspaceDto {
  id: string;
  root_path: string;
  repositories: RunInspectorWorkspaceRepositoryDto[];
  created_at: number;
}

export interface RunInspectorSessionDto {
  id: string;
  kind: "root" | "child";
}

export interface RunInspectorTaskDto {
  id: string;
  run_id: string;
  title: string;
  status: string;
  root_session_id: string | null;
  child_session_id: string | null;
  dispatch_title: string | null;
  purpose: string | null;
  source_event_id: string | null;
  created_at: number;
  updated_at: number | null;
}

export interface RunInspectorAttemptDto {
  id: string;
  task_id: string;
  status: string;
  child_session_id: string | null;
  worker_name: string | null;
  worker_config_path: string | null;
  purpose: string | null;
  harness: string | null;
  model: string | null;
  dispatch_call_id: string | null;
  response_id: string | null;
  turn_id: string | null;
  started_at: number | null;
  completed_at: number | null;
  failure_code: string | null;
  failure_message: string | null;
  source_event_id: string | null;
  created_at: number;
  updated_at: number | null;
}

export interface RunInspectorDependencyDto {
  task_id: string;
  depends_on_task_id: string;
}

export interface RunInspectorEventDto {
  source: string;
  source_event_id: string;
  event_type: string;
  run_id: string;
  payload: Record<string, unknown>;
  task_id: string | null;
  attempt_id: string | null;
  session_id: string | null;
  conversation_item_id: string | null;
}

export interface RunInspectorLeaseDto {
  id: string;
  run_id: string;
  attempt_id: string | null;
  child_session_id: string;
  host_id: string;
  repository_id: string;
  worktree_path: string;
  branch: string;
  owner_id: string;
  status: string;
  heartbeat_at: number;
  base_commit: string | null;
  output_commit: string | null;
  created_at: number;
  released_at: number | null;
}

export interface RunInspectorFailureDto {
  attempt_id: string | null;
  code: string;
  message: string;
}

export interface RunInspectorLogReferenceDto {
  session_id: string;
  href: string;
}

export interface RunInspectorArtifactReferenceDto {
  id: string;
  task_id: string | null;
  attempt_id: string | null;
  name: string;
  location: string;
  content_type: string | null;
  created_at: number;
}

export interface RunInspectorResponseDto {
  object: "run.inspector";
  run: RunInspectorRunDto;
  root_session_id: string | null;
  child_session_ids: string[];
  conversation_item_ids: string[];
  tasks: RunInspectorTaskDto[];
  attempts: RunInspectorAttemptDto[];
  failures: RunInspectorFailureDto[];
  agent_snapshot: RunInspectorAgentSnapshotDto | null;
  workspace: RunInspectorWorkspaceDto | null;
  sessions: RunInspectorSessionDto[];
  dependencies: RunInspectorDependencyDto[];
  events: RunInspectorEventDto[];
  leases: RunInspectorLeaseDto[];
  log_references: RunInspectorLogReferenceDto[];
  artifact_references: RunInspectorArtifactReferenceDto[];
}

export interface RunEventListDto {
  object: "list";
  data: RunInspectorEventDto[];
}

export interface RunStopDto {
  id: string;
  status: "stopping";
}

export interface RunApprovalDecisionDto {
  id: string;
  run_id: string;
  decision: "approve" | "deny";
}

export interface EvaluationEvidenceCountsDto {
  worktree: number;
  commit: number;
  artifact: number;
  test: number;
  session: number;
  conversation_item: number;
}

export interface RunEvaluationMetricsDto {
  task_completion_rate: number;
  attempt_success_rate: number;
  retry_count: number;
  blocked_count: number;
  blocked_duration_seconds: number;
  parallel_overlap_seconds: number;
  max_concurrency: number;
  worker_duration_seconds: number;
  parent_inbox_latency_seconds: number | null;
  parent_inbox_latency_samples: number;
  failure_categories: Record<string, number>;
  evidence_counts: EvaluationEvidenceCountsDto;
}

export interface WorkerEvaluationDto {
  worker_name: string;
  session_ids: string[];
  task_count: number;
  attempt_count: number;
  success_count: number;
  retry_count: number;
  blocked_count: number;
  blocked_duration_seconds: number;
  duration_seconds: number;
  failure_categories: Record<string, number>;
}

export interface RunEvaluationDto {
  object: "run.evaluation";
  id: string;
  run_id: string;
  evaluator: string;
  version: number;
  status: "preview" | "final";
  metrics: RunEvaluationMetricsDto;
  workers: WorkerEvaluationDto[];
  evidence_refs: string[];
  rubric: Record<string, unknown> | null;
  created_at: number;
  updated_at: number;
}

export class RunDtoParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunDtoParseError";
  }
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, path: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new RunDtoParseError(`${path} must be an object`);
  }
  return Object.fromEntries(Object.entries(value));
}

function exact(value: unknown, path: string, fields: readonly string[]): JsonObject {
  const result = object(value, path);
  const allowed = new Set(fields);
  for (const field of Object.keys(result)) {
    if (!allowed.has(field)) throw new RunDtoParseError(`${path}: unexpected field ${field}`);
  }
  return result;
}

function present(value: JsonObject, field: string, path: string): unknown {
  if (!(field in value)) throw new RunDtoParseError(`${path}.${field} is required`);
  return value[field];
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") throw new RunDtoParseError(`${path} must be a string`);
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : string(value, path);
}

function number(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new RunDtoParseError(`${path} must be a finite number`);
  }
  return value;
}

function nullableNumber(value: unknown, path: string): number | null {
  return value === null ? null : number(value, path);
}

function literal<T extends string>(value: unknown, expected: T, path: string): T {
  if (value !== expected) throw new RunDtoParseError(`${path} must be ${expected}`);
  return expected;
}

function oneOf<T extends string>(value: unknown, expected: readonly T[], path: string): T {
  const result = string(value, path);
  if (!expected.includes(result as T)) {
    throw new RunDtoParseError(`${path} must be one of ${expected.join(", ")}`);
  }
  return result as T;
}

function array<T>(value: unknown, path: string, parser: (item: unknown, path: string) => T): T[] {
  if (!Array.isArray(value)) throw new RunDtoParseError(`${path} must be an array`);
  return value.map((item, index) => parser(item, `${path}[${index}]`));
}

function stringArray(value: unknown, path: string): string[] {
  return array(value, path, string);
}

function numberMap(value: unknown, path: string): Record<string, number> {
  const result = object(value, path);
  return Object.fromEntries(
    Object.entries(result).map(([key, item]) => [key, number(item, `${path}.${key}`)]),
  );
}

const RUN_INSPECTOR_FIELDS = [
  "id",
  "actor_id",
  "auth_scope",
  "source",
  "source_event_id",
  "agent_id",
  "bundle_version",
  "bundle_digest",
  "bundle_location",
  "workspace_id",
  "root_session_id",
  "status",
  "created_at",
  "updated_at",
] as const;

function parseInspectorRunFields(data: JsonObject, path: string): RunInspectorRunDto {
  return {
    id: string(present(data, "id", path), `${path}.id`),
    actor_id: string(present(data, "actor_id", path), `${path}.actor_id`),
    auth_scope: string(present(data, "auth_scope", path), `${path}.auth_scope`),
    source: string(present(data, "source", path), `${path}.source`),
    source_event_id: string(present(data, "source_event_id", path), `${path}.source_event_id`),
    agent_id: string(present(data, "agent_id", path), `${path}.agent_id`),
    bundle_version: number(present(data, "bundle_version", path), `${path}.bundle_version`),
    bundle_digest: string(present(data, "bundle_digest", path), `${path}.bundle_digest`),
    bundle_location: string(present(data, "bundle_location", path), `${path}.bundle_location`),
    workspace_id: string(present(data, "workspace_id", path), `${path}.workspace_id`),
    root_session_id: nullableString(
      present(data, "root_session_id", path),
      `${path}.root_session_id`,
    ),
    status: string(present(data, "status", path), `${path}.status`),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
    updated_at: nullableNumber(present(data, "updated_at", path), `${path}.updated_at`),
  };
}

function parseInspectorRun(value: unknown, path: string): RunInspectorRunDto {
  return parseInspectorRunFields(exact(value, path, RUN_INSPECTOR_FIELDS), path);
}

function parseRun(value: unknown, path = "run"): RunDto {
  const data = exact(value, path, ["object", ...RUN_INSPECTOR_FIELDS]);
  return {
    object: literal(present(data, "object", path), "run", `${path}.object`),
    ...parseInspectorRunFields(data, path),
  };
}

function parseAgentSnapshot(value: unknown, path: string): RunInspectorAgentSnapshotDto {
  const data = exact(value, path, ["id", "bundle_version", "bundle_digest", "bundle_location"]);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    bundle_version: number(present(data, "bundle_version", path), `${path}.bundle_version`),
    bundle_digest: string(present(data, "bundle_digest", path), `${path}.bundle_digest`),
    bundle_location: string(present(data, "bundle_location", path), `${path}.bundle_location`),
  };
}

function parseRepository(value: unknown, path: string): RunInspectorWorkspaceRepositoryDto {
  const data = exact(value, path, ["id", "name", "path"]);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    name: string(present(data, "name", path), `${path}.name`),
    path: string(present(data, "path", path), `${path}.path`),
  };
}

function parseWorkspace(value: unknown, path: string): RunInspectorWorkspaceDto {
  const data = exact(value, path, ["id", "root_path", "repositories", "created_at"]);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    root_path: string(present(data, "root_path", path), `${path}.root_path`),
    repositories: array(
      present(data, "repositories", path),
      `${path}.repositories`,
      parseRepository,
    ),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
  };
}

function parseSession(value: unknown, path: string): RunInspectorSessionDto {
  const data = exact(value, path, ["id", "kind"]);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    kind: oneOf(present(data, "kind", path), ["root", "child"] as const, `${path}.kind`),
  };
}

function parseTask(value: unknown, path: string): RunInspectorTaskDto {
  const fields = [
    "id",
    "run_id",
    "title",
    "status",
    "root_session_id",
    "child_session_id",
    "dispatch_title",
    "purpose",
    "source_event_id",
    "created_at",
    "updated_at",
  ] as const;
  const data = exact(value, path, fields);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    run_id: string(present(data, "run_id", path), `${path}.run_id`),
    title: string(present(data, "title", path), `${path}.title`),
    status: string(present(data, "status", path), `${path}.status`),
    root_session_id: nullableString(
      present(data, "root_session_id", path),
      `${path}.root_session_id`,
    ),
    child_session_id: nullableString(
      present(data, "child_session_id", path),
      `${path}.child_session_id`,
    ),
    dispatch_title: nullableString(present(data, "dispatch_title", path), `${path}.dispatch_title`),
    purpose: nullableString(present(data, "purpose", path), `${path}.purpose`),
    source_event_id: nullableString(
      present(data, "source_event_id", path),
      `${path}.source_event_id`,
    ),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
    updated_at: nullableNumber(present(data, "updated_at", path), `${path}.updated_at`),
  };
}

function parseAttempt(value: unknown, path: string): RunInspectorAttemptDto {
  const fields = [
    "id",
    "task_id",
    "status",
    "child_session_id",
    "worker_name",
    "worker_config_path",
    "purpose",
    "harness",
    "model",
    "dispatch_call_id",
    "response_id",
    "turn_id",
    "started_at",
    "completed_at",
    "failure_code",
    "failure_message",
    "source_event_id",
    "created_at",
    "updated_at",
  ] as const;
  const data = exact(value, path, fields);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    task_id: string(present(data, "task_id", path), `${path}.task_id`),
    status: string(present(data, "status", path), `${path}.status`),
    child_session_id: nullableString(
      present(data, "child_session_id", path),
      `${path}.child_session_id`,
    ),
    worker_name: nullableString(present(data, "worker_name", path), `${path}.worker_name`),
    worker_config_path: nullableString(
      present(data, "worker_config_path", path),
      `${path}.worker_config_path`,
    ),
    purpose: nullableString(present(data, "purpose", path), `${path}.purpose`),
    harness: nullableString(present(data, "harness", path), `${path}.harness`),
    model: nullableString(present(data, "model", path), `${path}.model`),
    dispatch_call_id: nullableString(
      present(data, "dispatch_call_id", path),
      `${path}.dispatch_call_id`,
    ),
    response_id: nullableString(present(data, "response_id", path), `${path}.response_id`),
    turn_id: nullableString(present(data, "turn_id", path), `${path}.turn_id`),
    started_at: nullableNumber(present(data, "started_at", path), `${path}.started_at`),
    completed_at: nullableNumber(present(data, "completed_at", path), `${path}.completed_at`),
    failure_code: nullableString(present(data, "failure_code", path), `${path}.failure_code`),
    failure_message: nullableString(
      present(data, "failure_message", path),
      `${path}.failure_message`,
    ),
    source_event_id: nullableString(
      present(data, "source_event_id", path),
      `${path}.source_event_id`,
    ),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
    updated_at: nullableNumber(present(data, "updated_at", path), `${path}.updated_at`),
  };
}

function parseDependency(value: unknown, path: string): RunInspectorDependencyDto {
  const data = exact(value, path, ["task_id", "depends_on_task_id"]);
  return {
    task_id: string(present(data, "task_id", path), `${path}.task_id`),
    depends_on_task_id: string(
      present(data, "depends_on_task_id", path),
      `${path}.depends_on_task_id`,
    ),
  };
}

function parseEvent(value: unknown, path: string): RunInspectorEventDto {
  const fields = [
    "source",
    "source_event_id",
    "event_type",
    "run_id",
    "payload",
    "task_id",
    "attempt_id",
    "session_id",
    "conversation_item_id",
  ] as const;
  const data = exact(value, path, fields);
  return {
    source: string(present(data, "source", path), `${path}.source`),
    source_event_id: string(present(data, "source_event_id", path), `${path}.source_event_id`),
    event_type: string(present(data, "event_type", path), `${path}.event_type`),
    run_id: string(present(data, "run_id", path), `${path}.run_id`),
    payload: object(present(data, "payload", path), `${path}.payload`),
    task_id: nullableString(present(data, "task_id", path), `${path}.task_id`),
    attempt_id: nullableString(present(data, "attempt_id", path), `${path}.attempt_id`),
    session_id: nullableString(present(data, "session_id", path), `${path}.session_id`),
    conversation_item_id: nullableString(
      present(data, "conversation_item_id", path),
      `${path}.conversation_item_id`,
    ),
  };
}

function parseLease(value: unknown, path: string): RunInspectorLeaseDto {
  const fields = [
    "id",
    "run_id",
    "attempt_id",
    "child_session_id",
    "host_id",
    "repository_id",
    "worktree_path",
    "branch",
    "owner_id",
    "status",
    "heartbeat_at",
    "base_commit",
    "output_commit",
    "created_at",
    "released_at",
  ] as const;
  const data = exact(value, path, fields);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    run_id: string(present(data, "run_id", path), `${path}.run_id`),
    attempt_id: nullableString(present(data, "attempt_id", path), `${path}.attempt_id`),
    child_session_id: string(present(data, "child_session_id", path), `${path}.child_session_id`),
    host_id: string(present(data, "host_id", path), `${path}.host_id`),
    repository_id: string(present(data, "repository_id", path), `${path}.repository_id`),
    worktree_path: string(present(data, "worktree_path", path), `${path}.worktree_path`),
    branch: string(present(data, "branch", path), `${path}.branch`),
    owner_id: string(present(data, "owner_id", path), `${path}.owner_id`),
    status: string(present(data, "status", path), `${path}.status`),
    heartbeat_at: number(present(data, "heartbeat_at", path), `${path}.heartbeat_at`),
    base_commit: nullableString(present(data, "base_commit", path), `${path}.base_commit`),
    output_commit: nullableString(present(data, "output_commit", path), `${path}.output_commit`),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
    released_at: nullableNumber(present(data, "released_at", path), `${path}.released_at`),
  };
}

function parseFailure(value: unknown, path: string): RunInspectorFailureDto {
  const data = exact(value, path, ["attempt_id", "code", "message"]);
  return {
    attempt_id: nullableString(present(data, "attempt_id", path), `${path}.attempt_id`),
    code: string(present(data, "code", path), `${path}.code`),
    message: string(present(data, "message", path), `${path}.message`),
  };
}

function parseLogReference(value: unknown, path: string): RunInspectorLogReferenceDto {
  const data = exact(value, path, ["session_id", "href"]);
  return {
    session_id: string(present(data, "session_id", path), `${path}.session_id`),
    href: string(present(data, "href", path), `${path}.href`),
  };
}

function parseArtifactReference(value: unknown, path: string): RunInspectorArtifactReferenceDto {
  const data = exact(value, path, [
    "id",
    "task_id",
    "attempt_id",
    "name",
    "location",
    "content_type",
    "created_at",
  ]);
  return {
    id: string(present(data, "id", path), `${path}.id`),
    task_id: nullableString(present(data, "task_id", path), `${path}.task_id`),
    attempt_id: nullableString(present(data, "attempt_id", path), `${path}.attempt_id`),
    name: string(present(data, "name", path), `${path}.name`),
    location: string(present(data, "location", path), `${path}.location`),
    content_type: nullableString(present(data, "content_type", path), `${path}.content_type`),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
  };
}

export function parseRunInspectorResponse(value: unknown): RunInspectorResponseDto {
  const path = "run inspector";
  const fields = [
    "object",
    "run",
    "root_session_id",
    "child_session_ids",
    "conversation_item_ids",
    "tasks",
    "attempts",
    "failures",
    "agent_snapshot",
    "workspace",
    "sessions",
    "dependencies",
    "events",
    "leases",
    "log_references",
    "artifact_references",
  ] as const;
  const data = exact(value, path, fields);
  const snapshot = present(data, "agent_snapshot", path);
  const workspace = present(data, "workspace", path);
  return {
    object: literal(present(data, "object", path), "run.inspector", `${path}.object`),
    run: parseInspectorRun(present(data, "run", path), `${path}.run`),
    root_session_id: nullableString(
      present(data, "root_session_id", path),
      `${path}.root_session_id`,
    ),
    child_session_ids: stringArray(
      present(data, "child_session_ids", path),
      `${path}.child_session_ids`,
    ),
    conversation_item_ids: stringArray(
      present(data, "conversation_item_ids", path),
      `${path}.conversation_item_ids`,
    ),
    tasks: array(present(data, "tasks", path), `${path}.tasks`, parseTask),
    attempts: array(present(data, "attempts", path), `${path}.attempts`, parseAttempt),
    failures: array(present(data, "failures", path), `${path}.failures`, parseFailure),
    agent_snapshot:
      snapshot === null ? null : parseAgentSnapshot(snapshot, `${path}.agent_snapshot`),
    workspace: workspace === null ? null : parseWorkspace(workspace, `${path}.workspace`),
    sessions: array(present(data, "sessions", path), `${path}.sessions`, parseSession),
    dependencies: array(
      present(data, "dependencies", path),
      `${path}.dependencies`,
      parseDependency,
    ),
    events: array(present(data, "events", path), `${path}.events`, parseEvent),
    leases: array(present(data, "leases", path), `${path}.leases`, parseLease),
    log_references: array(
      present(data, "log_references", path),
      `${path}.log_references`,
      parseLogReference,
    ),
    artifact_references: array(
      present(data, "artifact_references", path),
      `${path}.artifact_references`,
      parseArtifactReference,
    ),
  };
}

function parseEvidenceCounts(value: unknown, path: string): EvaluationEvidenceCountsDto {
  const fields = ["worktree", "commit", "artifact", "test", "session", "conversation_item"];
  const data = exact(value, path, fields);
  return {
    worktree: number(present(data, "worktree", path), `${path}.worktree`),
    commit: number(present(data, "commit", path), `${path}.commit`),
    artifact: number(present(data, "artifact", path), `${path}.artifact`),
    test: number(present(data, "test", path), `${path}.test`),
    session: number(present(data, "session", path), `${path}.session`),
    conversation_item: number(
      present(data, "conversation_item", path),
      `${path}.conversation_item`,
    ),
  };
}

function parseEvaluationMetrics(value: unknown, path: string): RunEvaluationMetricsDto {
  const fields = [
    "task_completion_rate",
    "attempt_success_rate",
    "retry_count",
    "blocked_count",
    "blocked_duration_seconds",
    "parallel_overlap_seconds",
    "max_concurrency",
    "worker_duration_seconds",
    "parent_inbox_latency_seconds",
    "parent_inbox_latency_samples",
    "failure_categories",
    "evidence_counts",
  ] as const;
  const data = exact(value, path, fields);
  return {
    task_completion_rate: number(
      present(data, "task_completion_rate", path),
      `${path}.task_completion_rate`,
    ),
    attempt_success_rate: number(
      present(data, "attempt_success_rate", path),
      `${path}.attempt_success_rate`,
    ),
    retry_count: number(present(data, "retry_count", path), `${path}.retry_count`),
    blocked_count: number(present(data, "blocked_count", path), `${path}.blocked_count`),
    blocked_duration_seconds: number(
      present(data, "blocked_duration_seconds", path),
      `${path}.blocked_duration_seconds`,
    ),
    parallel_overlap_seconds: number(
      present(data, "parallel_overlap_seconds", path),
      `${path}.parallel_overlap_seconds`,
    ),
    max_concurrency: number(present(data, "max_concurrency", path), `${path}.max_concurrency`),
    worker_duration_seconds: number(
      present(data, "worker_duration_seconds", path),
      `${path}.worker_duration_seconds`,
    ),
    parent_inbox_latency_seconds: nullableNumber(
      present(data, "parent_inbox_latency_seconds", path),
      `${path}.parent_inbox_latency_seconds`,
    ),
    parent_inbox_latency_samples: number(
      present(data, "parent_inbox_latency_samples", path),
      `${path}.parent_inbox_latency_samples`,
    ),
    failure_categories: numberMap(
      present(data, "failure_categories", path),
      `${path}.failure_categories`,
    ),
    evidence_counts: parseEvidenceCounts(
      present(data, "evidence_counts", path),
      `${path}.evidence_counts`,
    ),
  };
}

function parseWorkerEvaluation(value: unknown, path: string): WorkerEvaluationDto {
  const fields = [
    "worker_name",
    "session_ids",
    "task_count",
    "attempt_count",
    "success_count",
    "retry_count",
    "blocked_count",
    "blocked_duration_seconds",
    "duration_seconds",
    "failure_categories",
  ] as const;
  const data = exact(value, path, fields);
  return {
    worker_name: string(present(data, "worker_name", path), `${path}.worker_name`),
    session_ids: stringArray(present(data, "session_ids", path), `${path}.session_ids`),
    task_count: number(present(data, "task_count", path), `${path}.task_count`),
    attempt_count: number(present(data, "attempt_count", path), `${path}.attempt_count`),
    success_count: number(present(data, "success_count", path), `${path}.success_count`),
    retry_count: number(present(data, "retry_count", path), `${path}.retry_count`),
    blocked_count: number(present(data, "blocked_count", path), `${path}.blocked_count`),
    blocked_duration_seconds: number(
      present(data, "blocked_duration_seconds", path),
      `${path}.blocked_duration_seconds`,
    ),
    duration_seconds: number(present(data, "duration_seconds", path), `${path}.duration_seconds`),
    failure_categories: numberMap(
      present(data, "failure_categories", path),
      `${path}.failure_categories`,
    ),
  };
}

export function parseRunEvaluationResponse(value: unknown): RunEvaluationDto {
  const path = "evaluation";
  const fields = [
    "object",
    "id",
    "run_id",
    "evaluator",
    "version",
    "status",
    "metrics",
    "workers",
    "evidence_refs",
    "rubric",
    "created_at",
    "updated_at",
  ] as const;
  const data = exact(value, path, fields);
  const rubric = present(data, "rubric", path);
  return {
    object: literal(present(data, "object", path), "run.evaluation", `${path}.object`),
    id: string(present(data, "id", path), `${path}.id`),
    run_id: string(present(data, "run_id", path), `${path}.run_id`),
    evaluator: string(present(data, "evaluator", path), `${path}.evaluator`),
    version: number(present(data, "version", path), `${path}.version`),
    status: oneOf(present(data, "status", path), ["preview", "final"] as const, `${path}.status`),
    metrics: parseEvaluationMetrics(present(data, "metrics", path), `${path}.metrics`),
    workers: array(present(data, "workers", path), `${path}.workers`, parseWorkerEvaluation),
    evidence_refs: stringArray(present(data, "evidence_refs", path), `${path}.evidence_refs`),
    rubric: rubric === null ? null : object(rubric, `${path}.rubric`),
    created_at: number(present(data, "created_at", path), `${path}.created_at`),
    updated_at: number(present(data, "updated_at", path), `${path}.updated_at`),
  };
}

async function read<T>(response: Response, parser: (value: unknown) => T): Promise<T> {
  if (!response.ok) await throwApiError(response);
  return parser(await response.json());
}

function parseRunList(value: unknown): RunListDto {
  const data = exact(value, "runList", ["object", "data"]);
  return {
    object: literal(present(data, "object", "runList"), "list", "runList.object"),
    data: array(present(data, "data", "runList"), "runList.data", parseRun),
  };
}

function parseEventList(value: unknown): RunEventListDto {
  const data = exact(value, "eventList", ["object", "data"]);
  return {
    object: literal(present(data, "object", "eventList"), "list", "eventList.object"),
    data: array(present(data, "data", "eventList"), "eventList.data", parseEvent),
  };
}

function parseStop(value: unknown): RunStopDto {
  const data = exact(value, "stop", ["id", "status"]);
  return {
    id: string(present(data, "id", "stop"), "stop.id"),
    status: literal(present(data, "status", "stop"), "stopping", "stop.status"),
  };
}

function parseApproval(value: unknown): RunApprovalDecisionDto {
  const data = exact(value, "approval", ["id", "run_id", "decision"]);
  return {
    id: string(present(data, "id", "approval"), "approval.id"),
    run_id: string(present(data, "run_id", "approval"), "approval.run_id"),
    decision: oneOf(
      present(data, "decision", "approval"),
      ["approve", "deny"] as const,
      "approval.decision",
    ),
  };
}

export async function createRun(input: CreateRunInput): Promise<RunDto> {
  return read(
    await authenticatedFetch("/v1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    (value) => parseRun(value, "run"),
  );
}

export async function listRuns(): Promise<RunListDto> {
  return read(await authenticatedFetch("/v1/runs"), parseRunList);
}

export async function getRunInspector(runId: string): Promise<RunInspectorResponseDto> {
  return read(
    await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}`),
    parseRunInspectorResponse,
  );
}

export async function listRunEvents(runId: string): Promise<RunEventListDto> {
  return read(
    await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}/events`),
    parseEventList,
  );
}

export async function stopRun(runId: string): Promise<RunStopDto> {
  return read(
    await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
    parseStop,
  );
}

async function decideRunApproval(
  runId: string,
  approvalId: string,
  decision: "approve" | "deny",
): Promise<RunApprovalDecisionDto> {
  return read(
    await authenticatedFetch(
      `/v1/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/${decision}`,
      { method: "POST" },
    ),
    parseApproval,
  );
}

export function approveRunApproval(
  runId: string,
  approvalId: string,
): Promise<RunApprovalDecisionDto> {
  return decideRunApproval(runId, approvalId, "approve");
}

export function denyRunApproval(
  runId: string,
  approvalId: string,
): Promise<RunApprovalDecisionDto> {
  return decideRunApproval(runId, approvalId, "deny");
}

export async function getRunEvaluation(runId: string): Promise<RunEvaluationDto> {
  return read(
    await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}/evaluation`),
    parseRunEvaluationResponse,
  );
}

export async function refreshRunEvaluation(runId: string): Promise<RunEvaluationDto> {
  return read(
    await authenticatedFetch(`/v1/runs/${encodeURIComponent(runId)}/evaluation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh: true }),
    }),
    parseRunEvaluationResponse,
  );
}
