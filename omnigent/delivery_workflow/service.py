"""Profile gate and state-machine rules for development delivery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from omnigent.entities.delivery_workflow import (
    DeliveryArtifact,
    DeliveryPhase,
    DeliveryRun,
    DeliveryStatus,
    DeliveryWorkflowSnapshot,
)
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runtime.agent_cache import AgentCache
from omnigent.stores.delivery_workflow_store import SqlAlchemyDeliveryWorkflowStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore

_PHASE_EDGES: dict[DeliveryPhase, frozenset[DeliveryPhase]] = {
    DeliveryPhase.INTAKE: frozenset({DeliveryPhase.PREFLIGHT}),
    DeliveryPhase.PREFLIGHT: frozenset({DeliveryPhase.REQUIREMENT}),
    DeliveryPhase.REQUIREMENT: frozenset(
        {DeliveryPhase.RESEARCH, DeliveryPhase.PROPOSAL}
    ),
    DeliveryPhase.RESEARCH: frozenset(
        {DeliveryPhase.REQUIREMENT, DeliveryPhase.PROPOSAL}
    ),
    DeliveryPhase.PROPOSAL: frozenset({DeliveryPhase.PLANNING}),
    DeliveryPhase.PLANNING: frozenset(
        {DeliveryPhase.PROPOSAL, DeliveryPhase.IMPLEMENTATION}
    ),
    DeliveryPhase.IMPLEMENTATION: frozenset(
        {DeliveryPhase.PROPOSAL, DeliveryPhase.INTEGRATION}
    ),
    DeliveryPhase.INTEGRATION: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.TESTING}
    ),
    DeliveryPhase.TESTING: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.VERIFICATION}
    ),
    DeliveryPhase.VERIFICATION: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.REVIEW}
    ),
    DeliveryPhase.REVIEW: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.KNOWLEDGE_CLOSE}
    ),
    DeliveryPhase.KNOWLEDGE_CLOSE: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.ARCHIVE}
    ),
    DeliveryPhase.ARCHIVE: frozenset({DeliveryPhase.PENDING_DELIVERY}),
    DeliveryPhase.PENDING_DELIVERY: frozenset(
        {DeliveryPhase.IMPLEMENTATION, DeliveryPhase.DELIVERED}
    ),
    DeliveryPhase.DELIVERED: frozenset(),
}
_TERMINAL_STATUSES = frozenset(
    {DeliveryStatus.FAILED, DeliveryStatus.CANCELLED, DeliveryStatus.COMPLETED}
)


class DeliveryWorkflowService:
    """Expose delivery state only for Runs whose frozen Bundle opts in."""

    def __init__(
        self,
        store: SqlAlchemyDeliveryWorkflowStore,
        run_store: SqlAlchemyRunStore,
        agent_cache: AgentCache,
    ) -> None:
        self._store = store
        self._runs = run_store
        self._agents = agent_cache

    def get(
        self,
        runtime_run_id: str,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
    ) -> DeliveryWorkflowSnapshot:
        profile_id = self.require_profile(
            runtime_run_id,
            actor_id=actor_id,
            workflow_agent_id=workflow_agent_id,
            workflow_session_id=workflow_session_id,
        )
        snapshot = self._store.get(
            runtime_run_id,
            profile_id=profile_id,
            owner_user_id=actor_id,
        )
        if snapshot is None:
            raise OmnigentError("Delivery workflow not found", code=ErrorCode.NOT_FOUND)
        return snapshot

    def put_plan(
        self,
        runtime_run_id: str,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
        expected_version: int,
        tasks: Iterable[Mapping[str, object]],
    ) -> DeliveryWorkflowSnapshot:
        profile_id = self.require_profile(
            runtime_run_id,
            actor_id=actor_id,
            workflow_agent_id=workflow_agent_id,
            workflow_session_id=workflow_session_id,
        )
        task_specs = tuple(tasks)
        _validate_plan(task_specs)
        return self._store.put_plan(
            runtime_run_id,
            profile_id=profile_id,
            owner_user_id=actor_id,
            expected_version=expected_version,
            tasks=task_specs,
        )

    def add_artifact(
        self,
        runtime_run_id: str,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
        kind: str,
        location: str,
        content_sha256: str,
        planned_task_id: str | None,
        metadata: Mapping[str, object],
    ) -> DeliveryArtifact:
        profile_id = self.require_profile(
            runtime_run_id,
            actor_id=actor_id,
            workflow_agent_id=workflow_agent_id,
            workflow_session_id=workflow_session_id,
        )
        return self._store.add_artifact(
            runtime_run_id,
            profile_id=profile_id,
            owner_user_id=actor_id,
            kind=kind,
            location=location,
            content_sha256=content_sha256,
            planned_task_id=planned_task_id,
            metadata=metadata,
        )

    def transition(
        self,
        runtime_run_id: str,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
        expected_phase: DeliveryPhase,
        expected_version: int,
        to_phase: DeliveryPhase,
        to_status: DeliveryStatus,
        idempotency_key: str,
        evidence_refs: Iterable[str],
    ) -> DeliveryWorkflowSnapshot:
        profile_id = self.require_profile(
            runtime_run_id,
            actor_id=actor_id,
            workflow_agent_id=workflow_agent_id,
            workflow_session_id=workflow_session_id,
        )
        evidence = tuple(evidence_refs)
        if not evidence:
            raise OmnigentError(
                "A delivery transition requires registered evidence",
                code=ErrorCode.INVALID_INPUT,
            )
        return self._store.transition(
            runtime_run_id,
            profile_id=profile_id,
            owner_user_id=actor_id,
            actor_id=actor_id,
            expected_phase=expected_phase,
            expected_version=expected_version,
            to_phase=to_phase,
            to_status=to_status,
            idempotency_key=idempotency_key,
            evidence_refs=evidence,
            validate=lambda current: _validate_transition(
                current,
                expected_phase,
                to_phase,
                to_status,
            ),
        )

    def require_profile(
        self,
        runtime_run_id: str,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
    ) -> str:
        """Return the profile declared by the Run's frozen Bundle or hide it."""
        run = self._runs.get_run(runtime_run_id)
        if (
            run is None
            or run.actor_id != actor_id
            or run.agent_id != workflow_agent_id
            or run.root_session_id != workflow_session_id
        ):
            raise OmnigentError("Run not found", code=ErrorCode.NOT_FOUND)
        loaded = self._agents.load(run.agent_id, run.bundle_location)
        workflow = loaded.spec.delivery_workflow
        if (
            workflow is None
            or workflow.profile != "zhuanspec-development"
            or workflow.role != "coordinator"
        ):
            raise OmnigentError("Delivery workflow not found", code=ErrorCode.NOT_FOUND)
        return workflow.profile

    def resolve_current_run_id(
        self,
        *,
        actor_id: str,
        workflow_agent_id: str,
        workflow_session_id: str,
    ) -> str:
        """Resolve the caller's Run from trusted root-session provenance."""
        run = self._runs.get_run_by_root_session_id(workflow_session_id)
        if (
            run is None
            or run.actor_id != actor_id
            or run.agent_id != workflow_agent_id
            or run.root_session_id != workflow_session_id
        ):
            raise OmnigentError("Delivery workflow not found", code=ErrorCode.NOT_FOUND)
        return run.id


def _validate_plan(tasks: tuple[Mapping[str, object], ...]) -> None:
    keys = tuple(str(task["task_key"]) for task in tasks)
    if len(keys) != len(set(keys)):
        raise OmnigentError("Delivery plan task keys must be unique", code=ErrorCode.INVALID_INPUT)
    known = set(keys)
    for task in tasks:
        key = str(task["task_key"])
        dependencies = tuple(str(item) for item in task.get("depends_on", ()))
        if key in dependencies or any(item not in known for item in dependencies):
            raise OmnigentError(
                f"Delivery plan task {key!r} has an invalid dependency",
                code=ErrorCode.INVALID_INPUT,
            )


def _validate_transition(
    current: DeliveryRun,
    expected_phase: DeliveryPhase,
    to_phase: DeliveryPhase,
    to_status: DeliveryStatus,
) -> None:
    if current.phase != expected_phase:
        raise OmnigentError("Delivery workflow phase conflict", code=ErrorCode.CONFLICT)
    if current.status in _TERMINAL_STATUSES:
        raise OmnigentError("Delivery workflow is terminal", code=ErrorCode.CONFLICT)
    if to_phase == current.phase:
        allowed = (
            (current.status == DeliveryStatus.ACTIVE and to_status == DeliveryStatus.BLOCKED)
            or (current.status == DeliveryStatus.BLOCKED and to_status == DeliveryStatus.ACTIVE)
            or to_status in {DeliveryStatus.FAILED, DeliveryStatus.CANCELLED}
        )
        if not allowed:
            raise OmnigentError("Illegal delivery status transition", code=ErrorCode.CONFLICT)
        return
    if current.status != DeliveryStatus.ACTIVE or to_phase not in _PHASE_EDGES[current.phase]:
        raise OmnigentError("Illegal delivery phase transition", code=ErrorCode.CONFLICT)
    expected_status = (
        DeliveryStatus.COMPLETED
        if to_phase == DeliveryPhase.DELIVERED
        else DeliveryStatus.ACTIVE
    )
    if to_status != expected_status:
        raise OmnigentError("Illegal delivery phase status", code=ErrorCode.CONFLICT)
