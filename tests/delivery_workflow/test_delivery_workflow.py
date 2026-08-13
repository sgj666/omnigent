from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from omnigent.db.db_models import OmnigentBase, SqlDeliveryRun, SqlDeliveryTransition
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker
from omnigent.delivery_workflow import DeliveryWorkflowService
from omnigent.entities.delivery_workflow import DeliveryPhase, DeliveryStatus
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.stores.delivery_workflow_store import SqlAlchemyDeliveryWorkflowStore


class _Runs:
    def __init__(self, *, actor_id: str = "alice") -> None:
        self.run = SimpleNamespace(
            id="1" * 32,
            actor_id=actor_id,
            agent_id="2" * 32,
            bundle_location=f"{'2' * 32}/{'a' * 64}",
            root_session_id="4" * 32,
        )

    def get_run(self, run_id: str) -> object | None:
        return self.run if run_id == self.run.id else None

    def get_run_by_root_session_id(self, session_id: str) -> object | None:
        return self.run if session_id == self.run.root_session_id else None


class _Cache:
    def __init__(self, *, profile: str | None = "zhuanspec-development") -> None:
        workflow = (
            SimpleNamespace(profile=profile, role="coordinator")
            if profile is not None
            else None
        )
        self.loaded = SimpleNamespace(spec=SimpleNamespace(delivery_workflow=workflow))
        self.calls: list[tuple[str, str]] = []

    def load(self, agent_id: str, bundle_location: str) -> object:
        self.calls.append((agent_id, bundle_location))
        return self.loaded


@pytest.fixture
def workflow(tmp_path: Path) -> tuple[DeliveryWorkflowService, str]:
    database = f"sqlite:///{tmp_path / 'delivery.db'}"
    OmnigentBase.metadata.create_all(get_or_create_engine(database))
    runs = _Runs()
    service = DeliveryWorkflowService(
        SqlAlchemyDeliveryWorkflowStore(database),
        runs,  # type: ignore[arg-type]
        _Cache(),  # type: ignore[arg-type]
    )
    return service, runs.run.id


def _plan(service: DeliveryWorkflowService, run_id: str) -> object:
    return service.put_plan(
        run_id,
        actor_id="alice",
        workflow_agent_id="2" * 32,
        workflow_session_id="4" * 32,
        expected_version=0,
        tasks=(
            {
                "task_key": "requirements",
                "title": "Analyze requirements",
                "owner_role": "requirement-analyst",
                "depends_on": (),
                "artifact_requirements": ("requirement-manifest",),
            },
        ),
    )


def test_plan_artifact_and_idempotent_evidence_transition(
    workflow: tuple[DeliveryWorkflowService, str],
) -> None:
    service, run_id = workflow
    initial = _plan(service, run_id)
    task = initial.planned_tasks[0]
    artifact = service.add_artifact(
        run_id,
        actor_id="alice",
        workflow_agent_id="2" * 32,
        workflow_session_id="4" * 32,
        kind="preflight-report",
        location="zhuanspec/changes/change-1/preflight.md",
        content_sha256="b" * 64,
        planned_task_id=task.id,
        metadata={"passed": True},
    )
    request = {
        "actor_id": "alice",
        "workflow_agent_id": "2" * 32,
        "workflow_session_id": "4" * 32,
        "expected_phase": DeliveryPhase.INTAKE,
        "expected_version": 1,
        "to_phase": DeliveryPhase.PREFLIGHT,
        "to_status": DeliveryStatus.ACTIVE,
        "idempotency_key": "preflight-1",
        "evidence_refs": (artifact.id,),
    }

    first = service.transition(run_id, **request)
    retry = service.transition(run_id, **request)

    assert first.run.phase == retry.run.phase == DeliveryPhase.PREFLIGHT
    assert first.run.version == retry.run.version == 2
    assert len(retry.transitions) == 1


def test_transition_rejects_illegal_jump_and_foreign_evidence(
    workflow: tuple[DeliveryWorkflowService, str],
) -> None:
    service, run_id = workflow
    _plan(service, run_id)

    with pytest.raises(OmnigentError) as jump:
        service.transition(
            run_id,
            actor_id="alice",
            workflow_agent_id="2" * 32,
            workflow_session_id="4" * 32,
            expected_phase=DeliveryPhase.INTAKE,
            expected_version=1,
            to_phase=DeliveryPhase.IMPLEMENTATION,
            to_status=DeliveryStatus.ACTIVE,
            idempotency_key="jump",
            evidence_refs=("3" * 32,),
        )

    assert jump.value.code == ErrorCode.CONFLICT
    assert service.get(
        run_id,
        actor_id="alice",
        workflow_agent_id="2" * 32,
        workflow_session_id="4" * 32,
    ).transitions == ()


def test_unconfigured_profile_is_hidden_and_creates_no_state(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'hidden.db'}"
    engine = get_or_create_engine(database)
    OmnigentBase.metadata.create_all(engine)
    runs = _Runs()
    service = DeliveryWorkflowService(
        SqlAlchemyDeliveryWorkflowStore(database),
        runs,  # type: ignore[arg-type]
        _Cache(profile=None),  # type: ignore[arg-type]
    )

    with pytest.raises(OmnigentError) as hidden:
        _plan(service, runs.run.id)

    assert hidden.value.code == ErrorCode.NOT_FOUND
    session_maker = make_managed_session_maker(engine)
    with session_maker() as session:
        assert session.query(SqlDeliveryRun).count() == 0
        assert session.query(SqlDeliveryTransition).count() == 0


def test_owner_and_expected_version_are_isolated(
    workflow: tuple[DeliveryWorkflowService, str],
) -> None:
    service, run_id = workflow
    _plan(service, run_id)

    with pytest.raises(OmnigentError) as owner:
        service.get(
            run_id,
            actor_id="bob",
            workflow_agent_id="2" * 32,
            workflow_session_id="4" * 32,
        )
    with pytest.raises(OmnigentError) as version:
        service.put_plan(
            run_id,
            actor_id="alice",
            workflow_agent_id="2" * 32,
            workflow_session_id="4" * 32,
            expected_version=9,
            tasks=(),
        )

    assert owner.value.code == ErrorCode.NOT_FOUND
    assert version.value.code == ErrorCode.CONFLICT


def test_current_run_is_resolved_from_trusted_root_session(
    workflow: tuple[DeliveryWorkflowService, str],
) -> None:
    service, run_id = workflow

    assert service.resolve_current_run_id(
        actor_id="alice",
        workflow_agent_id="2" * 32,
        workflow_session_id="4" * 32,
    ) == run_id
    with pytest.raises(OmnigentError) as wrong_session:
        service.resolve_current_run_id(
            actor_id="alice",
            workflow_agent_id="2" * 32,
            workflow_session_id="5" * 32,
        )
    assert wrong_session.value.code == ErrorCode.NOT_FOUND
