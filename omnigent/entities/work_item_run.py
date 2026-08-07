"""Product TaskRun entity persisted in ``work_item_runs``."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnigent.work_lifecycle import TaskRunState, TaskRunTrigger


@dataclass
class WorkItemRun:
    """One auditable execution attempt for a product Task."""

    id: str
    work_item_id: str
    owner_user_id: str | None
    session_id: str | None
    agent_id: str
    runtime_id: str
    workspace: str
    state: TaskRunState
    trigger: TaskRunTrigger
    retry_of_run_id: str | None
    queued_at: int
    started_at: int | None
    finished_at: int | None
    updated_at: int | None
    result_summary: str | None
    failure_code: str | None
    failure_message: str | None
    failure_retryable: bool
    artifact_refs: list[str] = field(default_factory=list)
    usage_refs: list[str] = field(default_factory=list)
