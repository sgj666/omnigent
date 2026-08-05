"""SQLAlchemy persistence for provider-neutral Session projections."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from omnigent.db.db_models import (
    SqlArtifact,
    SqlAttempt,
    SqlRun,
    SqlRunProjectionEvent,
    SqlRunTask,
    SqlTaskDependency,
    SqlWorkspaceBundle,
    SqlWorkspaceRepository,
    SqlWorktreeLease,
    current_workspace_id,
    worktree_path_cksum,
)
from omnigent.db.utils import get_or_create_engine, make_managed_session_maker, now_epoch
from omnigent.entities.run_projection import (
    Attempt,
    AttemptStatus,
    CreateRunResult,
    InspectorAgentSnapshot,
    InspectorArtifactReference,
    InspectorDependency,
    InspectorFailure,
    InspectorLogReference,
    InspectorRun,
    InspectorSessionReference,
    ProjectionEvent,
    ProjectionResult,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Workspace,
    WorkspaceRepository,
    WorktreeLease,
    WorktreeLeaseStatus,
)


class SqlAlchemyRunStore:
    """One transactional boundary for Run state and Session projections."""

    def __init__(self, storage_location: str) -> None:
        self.storage_location = storage_location
        self._session = make_managed_session_maker(get_or_create_engine(storage_location))

    def create_workspace(
        self,
        *,
        root_path: str,
        repositories: Iterable[tuple[str, str]],
    ) -> Workspace:
        workspace_id = uuid4().hex
        created_at = now_epoch()
        entries = tuple(repositories)
        with self._session() as session:
            session.add(
                SqlWorkspaceBundle(id=workspace_id, root_path=root_path, created_at=created_at)
            )
            for name, path in entries:
                session.add(
                    SqlWorkspaceRepository(
                        id=uuid4().hex,
                        workspace_bundle_id=workspace_id,
                        name=name,
                        path=path,
                        created_at=created_at,
                    )
                )
        workspace = self.get_workspace(workspace_id)
        assert workspace is not None
        return workspace

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self._session() as session:
            row = session.get(SqlWorkspaceBundle, (current_workspace_id(), workspace_id))
            if row is None:
                return None
            repositories = tuple(
                WorkspaceRepository(id=repo.id, name=repo.name, path=repo.path)
                for repo in session.execute(
                    select(SqlWorkspaceRepository)
                    .where(
                        SqlWorkspaceRepository.workspace_id == current_workspace_id(),
                        SqlWorkspaceRepository.workspace_bundle_id == workspace_id,
                    )
                    .order_by(SqlWorkspaceRepository.name, SqlWorkspaceRepository.id)
                ).scalars()
            )
            return Workspace(
                id=row.id,
                root_path=row.root_path,
                repositories=repositories,
                created_at=row.created_at,
            )

    def list_workspaces(self) -> tuple[Workspace, ...]:
        with self._session() as session:
            ids = tuple(
                session.execute(
                    select(SqlWorkspaceBundle.id)
                    .where(SqlWorkspaceBundle.workspace_id == current_workspace_id())
                    .order_by(SqlWorkspaceBundle.created_at, SqlWorkspaceBundle.id)
                ).scalars()
            )
        return tuple(
            workspace for workspace_id in ids if (workspace := self.get_workspace(workspace_id))
        )

    def create_run_idempotent(
        self,
        *,
        auth_scope: str,
        actor_id: str,
        source: str,
        source_event_id: str,
        agent_id: str,
        bundle_version: int,
        bundle_digest: str,
        bundle_location: str,
        workspace_id: str,
        root_session_id: str | None,
    ) -> CreateRunResult:
        existing = self.get_run_by_external_event(auth_scope, source, source_event_id)
        if existing is not None:
            return CreateRunResult(run=existing, created=False)
        row = SqlRun(
            id=uuid4().hex,
            team_id=None,
            agent_id=agent_id,
            bundle_version=bundle_version,
            bundle_digest=bundle_digest,
            bundle_location=bundle_location,
            root_session_id=root_session_id,
            legacy_state="native",
            workspace_bundle_id=workspace_id,
            source=source,
            source_event_id=source_event_id,
            auth_scope=auth_scope,
            status=(
                RunStatus.QUEUED.value if root_session_id is not None else RunStatus.CREATING.value
            ),
            account_id=actor_id,
            created_at=now_epoch(),
            updated_at=None,
        )
        try:
            with self._session() as session:
                session.add(row)
                session.flush()
        except IntegrityError:
            existing = self.get_run_by_external_event(auth_scope, source, source_event_id)
            if existing is None:
                raise
            return CreateRunResult(run=existing, created=False)
        created = self.get_run(row.id)
        assert created is not None
        return CreateRunResult(run=created, created=True)

    def bind_root_session(self, run_id: str, root_session_id: str) -> Run:
        """Bind a provisionally-created Run to its real Root Session."""
        with self._session() as session:
            row = session.get(SqlRun, (current_workspace_id(), run_id))
            if row is None:
                raise ValueError(f"Run not found: {run_id}")
            if row.root_session_id not in {None, root_session_id}:
                raise ValueError(f"Run {run_id!r} is already bound to another Root Session")
            row.root_session_id = root_session_id
            row.status = RunStatus.QUEUED.value
            row.updated_at = now_epoch()
        run = self.get_run(run_id)
        assert run is not None
        return run

    def mark_run_started(self, run_id: str) -> Run:
        """Record that the Root Session accepted the initial Run input."""
        with self._session() as session:
            row = session.get(SqlRun, (current_workspace_id(), run_id))
            if row is None:
                raise ValueError(f"Run not found: {run_id}")
            if row.root_session_id is None:
                raise ValueError(f"Run {run_id!r} has no Root Session")
            row.status = RunStatus.RUNNING.value
            row.updated_at = now_epoch()
        run = self.get_run(run_id)
        assert run is not None
        return run

    def mark_run_creation_failed(self, run_id: str, *, code: str, message: str) -> Run:
        """Persist an explicit terminal failure for a provisional Run."""
        with self._session() as session:
            row = session.get(SqlRun, (current_workspace_id(), run_id))
            if row is None:
                raise ValueError(f"Run not found: {run_id}")
            row.status = RunStatus.FAILED.value
            row.updated_at = now_epoch()
            session.add(
                SqlRunProjectionEvent(
                    id=uuid4().hex,
                    run_id=run_id,
                    task_id=None,
                    attempt_id=None,
                    session_id=row.root_session_id,
                    conversation_item_id=None,
                    source="run-service",
                    source_event_id=f"creation-failed:{run_id}",
                    event_type="run.creation.failed",
                    payload=json.dumps(
                        {"failure_code": code, "failure_message": message},
                        sort_keys=True,
                    ),
                    created_at=time.time_ns(),
                )
            )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def get_run_creation_failure(self, run_id: str) -> InspectorFailure | None:
        """Return the sanitized provisional-creation failure, when recorded."""
        for event in reversed(self.list_projection_events(run_id)):
            if event.event_type != "run.creation.failed":
                continue
            return InspectorFailure(
                attempt_id=None,
                code=str(event.payload.get("failure_code") or "run_creation_failed"),
                message=str(event.payload.get("failure_message") or "Run creation failed"),
            )
        return None

    def get_run_by_external_event(
        self, auth_scope: str, source: str, source_event_id: str
    ) -> Run | None:
        with self._session() as session:
            row = session.execute(
                select(SqlRun).where(
                    SqlRun.workspace_id == current_workspace_id(),
                    SqlRun.auth_scope == auth_scope,
                    SqlRun.source == source,
                    SqlRun.source_event_id == source_event_id,
                )
            ).scalar_one_or_none()
            return _run(row) if row is not None else None

    def get_run(self, run_id: str) -> Run | None:
        with self._session() as session:
            row = session.get(SqlRun, (current_workspace_id(), run_id))
            return _run(row) if row is not None else None

    def get_run_by_root_session_id(self, root_session_id: str) -> Run | None:
        with self._session() as session:
            row = session.execute(
                select(SqlRun).where(
                    SqlRun.workspace_id == current_workspace_id(),
                    SqlRun.root_session_id == root_session_id,
                )
            ).scalar_one_or_none()
            return _run(row) if row is not None else None

    def reserve_child_dispatch(
        self,
        *,
        run_id: str,
        child_session_id: str,
        worker_name: str,
        title: str,
        source_id: str,
    ) -> ProjectionResult:
        """Durably reserve the real Task/Attempt before Child runner launch."""
        event = ProjectionEvent(
            source="session-dispatch-reservation",
            source_event_id=f"{run_id}:{source_id}",
            event_type="dispatch.reserved",
            run_id=run_id,
            session_id=child_session_id,
            payload={
                "child_session_id": child_session_id,
                "worker_name": worker_name,
                "title": title,
            },
        )
        with self._session() as session:
            existing = session.execute(
                select(SqlRunProjectionEvent).where(
                    SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                    SqlRunProjectionEvent.source == event.source,
                    SqlRunProjectionEvent.source_event_id == event.source_event_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                task_row = session.get(SqlRunTask, (current_workspace_id(), existing.task_id))
                attempt_row = session.get(
                    SqlAttempt, (current_workspace_id(), existing.attempt_id)
                )
                if (
                    task_row is None
                    or attempt_row is None
                    or attempt_row.child_session_id != child_session_id
                    or attempt_row.worker_name != worker_name
                    or task_row.title != title
                ):
                    raise ValueError(
                        "dispatch source is already reserved for a different Run Child"
                    )
                return ProjectionResult(
                    created=False,
                    event=event,
                    task=_task(task_row) if task_row is not None else None,
                    attempt=_attempt(attempt_row) if attempt_row is not None else None,
                )
            run_row = session.get(SqlRun, (current_workspace_id(), run_id))
            if run_row is None:
                raise ValueError(f"Run not found: {run_id}")
            now = now_epoch()
            task_id = uuid4().hex
            attempt_id = uuid4().hex
            task_row = SqlRunTask(
                id=task_id,
                run_id=run_id,
                root_session_id=run_row.root_session_id,
                child_session_id=child_session_id,
                dispatch_title=title,
                purpose=None,
                source_event_id=event.source_event_id,
                title=title,
                status=TaskStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            attempt_row = SqlAttempt(
                id=attempt_id,
                task_id=task_id,
                agent_profile_id=None,
                child_session_id=child_session_id,
                worker_name=worker_name,
                worker_config_path=None,
                purpose=None,
                harness=None,
                model=None,
                dispatch_call_id=None,
                response_id=None,
                turn_id=None,
                started_at=None,
                completed_at=None,
                failure_code=None,
                failure_message=None,
                retry_of_attempt_id=None,
                source_event_id=event.source_event_id,
                status=AttemptStatus.QUEUED.value,
                created_at=now,
                updated_at=now,
            )
            session.add_all((task_row, attempt_row))
            session.add(
                SqlRunProjectionEvent(
                    id=uuid4().hex,
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    session_id=child_session_id,
                    conversation_item_id=None,
                    source=event.source,
                    source_event_id=event.source_event_id,
                    event_type=event.event_type,
                    payload=json.dumps(event.payload, sort_keys=True),
                    created_at=time.time_ns(),
                )
            )
            session.flush()
            return ProjectionResult(
                created=True,
                event=event,
                task=_task(task_row),
                attempt=_attempt(attempt_row),
            )

    def fail_reserved_child_dispatch(
        self,
        run_id: str,
        child_session_id: str,
        *,
        code: str,
        message: str,
    ) -> None:
        """Terminalize a reservation whose Child could not be created."""
        with self._session() as session:
            pair = session.execute(
                select(SqlRunTask, SqlAttempt)
                .join(
                    SqlAttempt,
                    (
                        (SqlAttempt.workspace_id == SqlRunTask.workspace_id)
                        & (SqlAttempt.task_id == SqlRunTask.id)
                    ),
                )
                .where(
                    SqlRunTask.workspace_id == current_workspace_id(),
                    SqlRunTask.run_id == run_id,
                    SqlAttempt.child_session_id == child_session_id,
                    SqlAttempt.status == AttemptStatus.QUEUED.value,
                )
                .order_by(SqlAttempt.created_at.desc(), SqlAttempt.id.desc())
            ).first()
            if pair is None:
                return
            task_row, attempt_row = pair
            now = now_epoch()
            task_row.status = TaskStatus.FAILED.value
            task_row.updated_at = now
            attempt_row.status = AttemptStatus.FAILED.value
            attempt_row.completed_at = now
            attempt_row.failure_code = code
            attempt_row.failure_message = message
            attempt_row.updated_at = now
            session.add(
                SqlRunProjectionEvent(
                    id=uuid4().hex,
                    run_id=run_id,
                    task_id=task_row.id,
                    attempt_id=attempt_row.id,
                    session_id=child_session_id,
                    conversation_item_id=None,
                    source="session-dispatch-reservation",
                    source_event_id=f"reservation-failed:{attempt_row.id}",
                    event_type="session.failed",
                    payload=json.dumps(
                        {"failure_code": code, "failure_message": message},
                        sort_keys=True,
                    ),
                    created_at=time.time_ns(),
                )
            )
            run_row = session.get(SqlRun, (current_workspace_id(), run_id))
            if run_row is not None:
                session.flush()
                _recompute_run_status(session, run_row, now)

    def list_runs(self, *, actor_id: str | None = None) -> tuple[Run, ...]:
        with self._session() as session:
            statement = select(SqlRun).where(SqlRun.workspace_id == current_workspace_id())
            if actor_id is not None:
                statement = statement.where(SqlRun.account_id == actor_id)
            rows = session.execute(
                statement.order_by(SqlRun.created_at.desc(), SqlRun.id.desc())
            ).scalars()
            return tuple(_run(row) for row in rows if row.agent_id is not None)

    def apply_projection_event(self, event: ProjectionEvent) -> ProjectionResult:
        with self._session() as session:
            existing = session.execute(
                select(SqlRunProjectionEvent).where(
                    SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                    SqlRunProjectionEvent.source == event.source,
                    SqlRunProjectionEvent.source_event_id == event.source_event_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                task_row = (
                    session.get(SqlRunTask, (current_workspace_id(), existing.task_id))
                    if existing.task_id
                    else None
                )
                attempt_row = (
                    session.get(SqlAttempt, (current_workspace_id(), existing.attempt_id))
                    if existing.attempt_id
                    else None
                )
                return ProjectionResult(
                    created=False,
                    event=event,
                    task=_task(task_row) if task_row else None,
                    attempt=_attempt(attempt_row) if attempt_row else None,
                )

            run_row = session.get(SqlRun, (current_workspace_id(), event.run_id))
            if run_row is None:
                raise ValueError(f"Run not found: {event.run_id}")
            now = now_epoch()
            task_row: SqlRunTask | None = None
            attempt_row: SqlAttempt | None = None
            task_id = event.task_id
            attempt_id = event.attempt_id

            if event.event_type == "dispatch.created":
                child_session_id = _required_payload(event, "child_session_id")
                title = _required_payload(event, "title")
                worker_name = _optional_payload(event, "worker_name")
                dispatch_call_id = _optional_payload(event, "dispatch_call_id")
                explicit_logical_task = _optional_payload(event, "logical_task_id")
                reserved = session.execute(
                    select(SqlRunTask, SqlAttempt)
                    .join(
                        SqlAttempt,
                        (
                            (SqlAttempt.workspace_id == SqlRunTask.workspace_id)
                            & (SqlAttempt.task_id == SqlRunTask.id)
                        ),
                    )
                    .where(
                        SqlRunTask.workspace_id == current_workspace_id(),
                        SqlRunTask.run_id == event.run_id,
                        SqlAttempt.child_session_id == child_session_id,
                        SqlAttempt.status.in_(
                            (AttemptStatus.QUEUED.value, AttemptStatus.RUNNING.value)
                        ),
                        (
                            SqlAttempt.dispatch_call_id.is_(None)
                            | (SqlAttempt.dispatch_call_id == dispatch_call_id)
                        ),
                    )
                    .order_by(SqlAttempt.created_at.desc(), SqlAttempt.id.desc())
                ).first()
                if reserved is not None:
                    task_row, attempt_row = reserved
                    task_id = task_row.id
                    attempt_id = attempt_row.id
                    if attempt_row.status == AttemptStatus.QUEUED.value:
                        task_row.status = TaskStatus.RUNNING.value
                        task_row.updated_at = now
                        attempt_row.dispatch_call_id = dispatch_call_id
                        attempt_row.worker_config_path = _optional_payload(
                            event, "worker_config_path"
                        )
                        attempt_row.purpose = _optional_payload(event, "purpose")
                        attempt_row.harness = _optional_payload(event, "harness")
                        attempt_row.model = _optional_payload(event, "model")
                        attempt_row.started_at = now
                        attempt_row.updated_at = now
                        attempt_row.status = AttemptStatus.RUNNING.value
                else:
                    existing_task: SqlRunTask | None = None
                    if explicit_logical_task is None:
                        existing_task = (
                            session.execute(
                                select(SqlRunTask)
                                .join(
                                    SqlAttempt,
                                    (
                                        (SqlAttempt.workspace_id == SqlRunTask.workspace_id)
                                        & (SqlAttempt.task_id == SqlRunTask.id)
                                    ),
                                )
                                .where(
                                    SqlRunTask.workspace_id == current_workspace_id(),
                                    SqlRunTask.run_id == event.run_id,
                                    SqlRunTask.title == title,
                                    SqlAttempt.worker_name == worker_name,
                                )
                                .order_by(SqlRunTask.created_at, SqlRunTask.id)
                            )
                            .scalars()
                            .first()
                        )
                    if (
                        existing_task is not None
                        and existing_task.child_session_id != child_session_id
                    ):
                        raise ValueError(
                            "dispatch for an existing worker/title must use its current "
                            "Child Session; set payload.logical_task_id for an explicit "
                            "new logical task"
                        )
                    task_id = existing_task.id if existing_task is not None else uuid4().hex
                    attempt_id = uuid4().hex
                    if existing_task is None:
                        task_row = SqlRunTask(
                            id=task_id,
                            run_id=event.run_id,
                            root_session_id=run_row.root_session_id,
                            child_session_id=child_session_id,
                            dispatch_title=title,
                            purpose=_optional_payload(event, "purpose"),
                            source_event_id=event.source_event_id,
                            title=title,
                            status=TaskStatus.RUNNING.value,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(task_row)
                    else:
                        task_row = existing_task
                        task_row.status = TaskStatus.RUNNING.value
                        task_row.updated_at = now
                    attempt_row = SqlAttempt(
                        id=attempt_id,
                        task_id=task_id,
                        agent_profile_id=None,
                        child_session_id=child_session_id,
                        worker_name=worker_name,
                        worker_config_path=_optional_payload(event, "worker_config_path"),
                        purpose=_optional_payload(event, "purpose"),
                        harness=_optional_payload(event, "harness"),
                        model=_optional_payload(event, "model"),
                        dispatch_call_id=_optional_payload(event, "dispatch_call_id"),
                        response_id=None,
                        turn_id=None,
                        started_at=now,
                        completed_at=None,
                        failure_code=None,
                        failure_message=None,
                        retry_of_attempt_id=None,
                        source_event_id=event.source_event_id,
                        status=AttemptStatus.RUNNING.value,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(attempt_row)
                run_row.status = RunStatus.RUNNING.value
                run_row.updated_at = now
            elif event.event_type in {
                "session.completed",
                "session.failed",
                "session.cancelled",
                "session.blocked",
                "session.running",
            }:
                if task_id is None or attempt_id is None:
                    raise ValueError("lifecycle projection requires task_id and attempt_id")
                task_row = session.get(SqlRunTask, (current_workspace_id(), task_id))
                attempt_row = session.get(SqlAttempt, (current_workspace_id(), attempt_id))
                if task_row is None or attempt_row is None:
                    raise ValueError("lifecycle projection references unknown task or attempt")
                lifecycle = {
                    "session.completed": (TaskStatus.COMPLETED, AttemptStatus.SUCCEEDED),
                    "session.failed": (TaskStatus.FAILED, AttemptStatus.FAILED),
                    "session.cancelled": (TaskStatus.CANCELLED, AttemptStatus.CANCELLED),
                    "session.blocked": (TaskStatus.BLOCKED, AttemptStatus.BLOCKED),
                    "session.running": (TaskStatus.RUNNING, AttemptStatus.RUNNING),
                }[event.event_type]
                task_row.status = lifecycle[0].value
                task_row.updated_at = now
                attempt_row.status = lifecycle[1].value
                attempt_row.completed_at = (
                    now
                    if event.event_type
                    in {"session.completed", "session.failed", "session.cancelled"}
                    else None
                )
                attempt_row.updated_at = now
                attempt_row.failure_code = _optional_payload(event, "failure_code")
                attempt_row.failure_message = _optional_payload(event, "failure_message")
                response_id = _optional_payload(event, "response_id")
                if response_id is not None:
                    attempt_row.response_id = response_id
                session.flush()
                _recompute_run_status(session, run_row, now)
            elif event.event_type == "plan.dependency":
                task_id = _required_payload(event, "task_id")
                depends_on = _required_payload(event, "depends_on_task_id")
                session.add(
                    SqlTaskDependency(
                        id=uuid4().hex,
                        task_id=task_id,
                        depends_on_task_id=depends_on,
                        created_at=now,
                    )
                )

            event_row = SqlRunProjectionEvent(
                id=uuid4().hex,
                run_id=event.run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                session_id=event.session_id,
                conversation_item_id=event.conversation_item_id,
                source=event.source,
                source_event_id=event.source_event_id,
                event_type=event.event_type,
                payload=json.dumps(event.payload, sort_keys=True),
                created_at=time.time_ns(),
            )
            session.add(event_row)
            session.flush()
            return ProjectionResult(
                created=True,
                event=event,
                task=_task(task_row) if task_row else None,
                attempt=_attempt(attempt_row) if attempt_row else None,
            )

    def reserve_followup_dispatch(
        self,
        *,
        run_id: str,
        child_session_id: str,
        source_id: str,
    ) -> ProjectionResult:
        """Reserve one new Attempt on an existing Child's logical Task."""
        event = ProjectionEvent(
            source="session-followup-reservation",
            source_event_id=f"{run_id}:{source_id}",
            event_type="dispatch.reserved",
            run_id=run_id,
            session_id=child_session_id,
            payload={"child_session_id": child_session_id},
        )
        with self._session() as session:
            existing = session.execute(
                select(SqlRunProjectionEvent).where(
                    SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                    SqlRunProjectionEvent.source == event.source,
                    SqlRunProjectionEvent.source_event_id == event.source_event_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                task_row = session.get(
                    SqlRunTask,
                    (current_workspace_id(), existing.task_id),
                )
                attempt_row = session.get(
                    SqlAttempt,
                    (current_workspace_id(), existing.attempt_id),
                )
                if task_row is None or attempt_row is None:
                    raise ValueError("follow-up reservation references missing Task/Attempt")
                return ProjectionResult(
                    created=False,
                    event=event,
                    task=_task(task_row),
                    attempt=_attempt(attempt_row),
                )
            pair = session.execute(
                select(SqlRunTask, SqlAttempt)
                .join(
                    SqlAttempt,
                    (
                        (SqlAttempt.workspace_id == SqlRunTask.workspace_id)
                        & (SqlAttempt.task_id == SqlRunTask.id)
                    ),
                )
                .where(
                    SqlRunTask.workspace_id == current_workspace_id(),
                    SqlRunTask.run_id == run_id,
                    SqlAttempt.child_session_id == child_session_id,
                )
                .order_by(SqlAttempt.created_at.desc(), SqlAttempt.id.desc())
            ).first()
            if pair is None:
                raise ValueError("Run Child has no logical Task to continue")
            task_row, previous_attempt = pair
            terminal_task_statuses = {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.BLOCKED.value,
            }
            if task_row.status not in terminal_task_statuses:
                raise ValueError("Run Child already has a queued or running Attempt")
            from sqlalchemy import update

            claimed = session.execute(
                update(SqlRunTask)
                .where(
                    SqlRunTask.workspace_id == current_workspace_id(),
                    SqlRunTask.id == task_row.id,
                    SqlRunTask.status.in_(terminal_task_statuses),
                )
                .values(status=TaskStatus.PENDING.value, updated_at=now_epoch())
            )
            if claimed.rowcount != 1:
                raise ValueError("Run Child follow-up was reserved concurrently")
            now = max(now_epoch(), previous_attempt.created_at + 1)
            attempt_row = SqlAttempt(
                id=uuid4().hex,
                task_id=task_row.id,
                agent_profile_id=previous_attempt.agent_profile_id,
                child_session_id=child_session_id,
                worker_name=previous_attempt.worker_name,
                worker_config_path=previous_attempt.worker_config_path,
                purpose=previous_attempt.purpose,
                harness=previous_attempt.harness,
                model=previous_attempt.model,
                dispatch_call_id=None,
                response_id=None,
                turn_id=None,
                started_at=None,
                completed_at=None,
                failure_code=None,
                failure_message=None,
                retry_of_attempt_id=previous_attempt.id,
                source_event_id=event.source_event_id,
                status=AttemptStatus.QUEUED.value,
                created_at=now,
                updated_at=now,
            )
            session.add(attempt_row)
            session.add(
                SqlRunProjectionEvent(
                    id=uuid4().hex,
                    run_id=run_id,
                    task_id=task_row.id,
                    attempt_id=attempt_row.id,
                    session_id=child_session_id,
                    conversation_item_id=None,
                    source=event.source,
                    source_event_id=event.source_event_id,
                    event_type=event.event_type,
                    payload=json.dumps(event.payload, sort_keys=True),
                    created_at=time.time_ns(),
                )
            )
            session.flush()
            return ProjectionResult(
                created=True,
                event=event,
                task=_task(task_row),
                attempt=_attempt(attempt_row),
            )

    def claim_followup_dispatch(
        self,
        *,
        run_id: str,
        child_session_id: str,
        source_id: str,
        idempotency_key: str,
    ) -> tuple[str, Attempt]:
        """CAS a reserved follow-up from prepared to dispatching."""
        source_event_id = f"{run_id}:{source_id}"
        with self._session() as session:
            event_row = session.execute(
                select(SqlRunProjectionEvent).where(
                    SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                    SqlRunProjectionEvent.source == "session-followup-reservation",
                    SqlRunProjectionEvent.source_event_id == source_event_id,
                    SqlRunProjectionEvent.session_id == child_session_id,
                )
            ).scalar_one_or_none()
            if event_row is None or event_row.attempt_id is None:
                raise ValueError("Run Child follow-up reservation does not exist")
            attempt_row = session.get(
                SqlAttempt,
                (current_workspace_id(), event_row.attempt_id),
            )
            if attempt_row is None:
                raise ValueError("Run Child follow-up Attempt does not exist")
            if (
                attempt_row.status == AttemptStatus.RUNNING.value
                and attempt_row.dispatch_call_id == idempotency_key
            ):
                return "accepted", _attempt(attempt_row)
            if attempt_row.status != AttemptStatus.QUEUED.value:
                return "failed", _attempt(attempt_row)
            claimed = session.execute(
                update(SqlAttempt)
                .where(
                    SqlAttempt.workspace_id == current_workspace_id(),
                    SqlAttempt.id == attempt_row.id,
                    SqlAttempt.status == AttemptStatus.QUEUED.value,
                    SqlAttempt.dispatch_call_id.is_(None),
                )
                .values(dispatch_call_id=idempotency_key, updated_at=now_epoch())
            )
            if claimed.rowcount == 1:
                session.flush()
                refreshed = session.get(
                    SqlAttempt,
                    (current_workspace_id(), attempt_row.id),
                    populate_existing=True,
                )
                assert refreshed is not None
                return "claimed", _attempt(refreshed)
            session.expire_all()
            current = session.get(
                SqlAttempt,
                (current_workspace_id(), attempt_row.id),
            )
            if current is None:
                raise ValueError("Run Child follow-up Attempt disappeared")
            if current.dispatch_call_id == idempotency_key:
                return (
                    "accepted" if current.status == AttemptStatus.RUNNING.value else "dispatching",
                    _attempt(current),
                )
            return "conflict", _attempt(current)

    def reset_followup_dispatch_claim(
        self,
        *,
        attempt_id: str,
        idempotency_key: str,
    ) -> bool:
        """Return an ambiguously failed dispatch to prepared for safe runner-key retry."""
        with self._session() as session:
            reset = session.execute(
                update(SqlAttempt)
                .where(
                    SqlAttempt.workspace_id == current_workspace_id(),
                    SqlAttempt.id == attempt_id,
                    SqlAttempt.status == AttemptStatus.QUEUED.value,
                    SqlAttempt.dispatch_call_id == idempotency_key,
                )
                .values(dispatch_call_id=None, updated_at=now_epoch())
            )
            return reset.rowcount == 1

    def accept_followup_dispatch(
        self,
        *,
        run_id: str,
        attempt_id: str,
        idempotency_key: str,
    ) -> Attempt:
        """Durably commit runner acceptance before optional projection observers run."""
        with self._session() as session:
            now = now_epoch()
            accepted = session.execute(
                update(SqlAttempt)
                .where(
                    SqlAttempt.workspace_id == current_workspace_id(),
                    SqlAttempt.id == attempt_id,
                    SqlAttempt.status == AttemptStatus.QUEUED.value,
                    SqlAttempt.dispatch_call_id == idempotency_key,
                )
                .values(
                    status=AttemptStatus.RUNNING.value,
                    started_at=now,
                    updated_at=now,
                )
            )
            attempt_row = session.get(
                SqlAttempt,
                (current_workspace_id(), attempt_id),
                populate_existing=True,
            )
            if attempt_row is None or attempt_row.dispatch_call_id != idempotency_key:
                raise ValueError("Run Child follow-up dispatch claim changed")
            if accepted.rowcount != 1 and attempt_row.status != AttemptStatus.RUNNING.value:
                raise ValueError("Run Child follow-up was not accepted from dispatching")
            task_row = session.get(
                SqlRunTask,
                (current_workspace_id(), attempt_row.task_id),
            )
            run_row = session.get(SqlRun, (current_workspace_id(), run_id))
            if task_row is None or run_row is None:
                raise ValueError("Run Child follow-up Task/Run disappeared")
            task_row.status = TaskStatus.RUNNING.value
            task_row.updated_at = now
            run_row.status = RunStatus.RUNNING.value
            run_row.updated_at = now
            session.flush()
            return _attempt(attempt_row)

    def list_tasks(self, run_id: str) -> tuple[Task, ...]:
        with self._session() as session:
            rows = session.execute(
                select(SqlRunTask)
                .where(
                    SqlRunTask.workspace_id == current_workspace_id(),
                    SqlRunTask.run_id == run_id,
                )
                .order_by(SqlRunTask.created_at, SqlRunTask.id)
            ).scalars()
            return tuple(_task(row) for row in rows)

    def list_attempts(self, run_id: str) -> tuple[Attempt, ...]:
        task_ids = tuple(task.id for task in self.list_tasks(run_id))
        if not task_ids:
            return ()
        with self._session() as session:
            rows = session.execute(
                select(SqlAttempt)
                .where(
                    SqlAttempt.workspace_id == current_workspace_id(),
                    SqlAttempt.task_id.in_(task_ids),
                )
                .order_by(SqlAttempt.created_at, SqlAttempt.id)
            ).scalars()
            return tuple(_attempt(row) for row in rows)

    def get_attempt(self, attempt_id: str) -> Attempt | None:
        with self._session() as session:
            row = session.get(SqlAttempt, (current_workspace_id(), attempt_id))
            return _attempt(row) if row is not None else None

    def get_latest_attempt_for_child(
        self, run_id: str, child_session_id: str
    ) -> tuple[Task, Attempt] | None:
        with self._session() as session:
            row = session.execute(
                select(SqlRunTask, SqlAttempt)
                .join(
                    SqlAttempt,
                    (
                        (SqlAttempt.workspace_id == SqlRunTask.workspace_id)
                        & (SqlAttempt.task_id == SqlRunTask.id)
                    ),
                )
                .where(
                    SqlRunTask.workspace_id == current_workspace_id(),
                    SqlRunTask.run_id == run_id,
                    SqlAttempt.child_session_id == child_session_id,
                )
                .order_by(SqlAttempt.created_at.desc(), SqlAttempt.id.desc())
            ).first()
            if row is None:
                return None
            return _task(row[0]), _attempt(row[1])

    def list_dependencies(self, run_id: str) -> tuple[tuple[str, str], ...]:
        task_ids = tuple(task.id for task in self.list_tasks(run_id))
        if not task_ids:
            return ()
        with self._session() as session:
            rows = session.execute(
                select(SqlTaskDependency)
                .where(
                    SqlTaskDependency.workspace_id == current_workspace_id(),
                    SqlTaskDependency.task_id.in_(task_ids),
                )
                .order_by(SqlTaskDependency.created_at, SqlTaskDependency.id)
            ).scalars()
            return tuple((row.task_id, row.depends_on_task_id) for row in rows)

    def inspect_run(self, run_id: str) -> InspectorRun:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        tasks = self.list_tasks(run_id)
        attempts = self.list_attempts(run_id)
        with self._session() as session:
            events = tuple(
                session.execute(
                    select(SqlRunProjectionEvent)
                    .where(
                        SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                        SqlRunProjectionEvent.run_id == run_id,
                    )
                    .order_by(SqlRunProjectionEvent.created_at, SqlRunProjectionEvent.id)
                ).scalars()
            )
            artifacts = tuple(
                session.execute(
                    select(SqlArtifact)
                    .where(
                        SqlArtifact.workspace_id == current_workspace_id(),
                        SqlArtifact.run_id == run_id,
                    )
                    .order_by(SqlArtifact.created_at, SqlArtifact.id)
                ).scalars()
            )
        projection_events = self.list_projection_events(run_id)
        child_session_ids = tuple(
            dict.fromkeys(
                tuple(
                    attempt.child_session_id
                    for attempt in attempts
                    if attempt.child_session_id is not None
                )
                + tuple(
                    event.session_id
                    for event in projection_events
                    if event.event_type == "session.child.created" and event.session_id is not None
                )
            )
        )
        session_ids = tuple(
            session_id
            for session_id in (run.root_session_id, *child_session_ids)
            if session_id is not None
        )
        creation_failures = tuple(
            InspectorFailure(
                attempt_id=None,
                code=str(event.payload.get("failure_code") or "run_creation_failed"),
                message=str(event.payload.get("failure_message") or "Run creation failed"),
            )
            for event in projection_events
            if event.event_type == "run.creation.failed"
        )
        return InspectorRun(
            run=run,
            root_session_id=run.root_session_id,
            child_session_ids=child_session_ids,
            conversation_item_ids=tuple(
                event.conversation_item_id
                for event in events
                if event.conversation_item_id is not None
            ),
            tasks=tasks,
            attempts=attempts,
            failures=creation_failures
            + tuple(
                InspectorFailure(
                    attempt_id=attempt.id,
                    code=attempt.failure_code or "unknown_failure",
                    message=attempt.failure_message or "Session failed without a detailed reason",
                )
                for attempt in attempts
                if attempt.status in {AttemptStatus.FAILED, AttemptStatus.BLOCKED}
            ),
            agent_snapshot=InspectorAgentSnapshot(
                id=run.agent_id,
                bundle_version=run.bundle_version,
                bundle_digest=run.bundle_digest,
                bundle_location=run.bundle_location,
            ),
            workspace=self.get_workspace(run.workspace_id),
            sessions=tuple(
                InspectorSessionReference(
                    id=session_id,
                    kind="root" if session_id == run.root_session_id else "child",
                )
                for session_id in session_ids
            ),
            dependencies=tuple(
                InspectorDependency(task_id=task_id, depends_on_task_id=depends_on_task_id)
                for task_id, depends_on_task_id in self.list_dependencies(run_id)
            ),
            events=projection_events,
            leases=self.list_active_worktree_leases(run_id),
            log_references=tuple(
                InspectorLogReference(
                    session_id=session_id,
                    href=f"/v1/sessions/{session_id}/items",
                )
                for session_id in session_ids
            ),
            artifact_references=tuple(
                InspectorArtifactReference(
                    id=artifact.id,
                    task_id=artifact.task_id,
                    attempt_id=artifact.attempt_id,
                    name=artifact.name,
                    location=artifact.location,
                    content_type=artifact.content_type,
                    created_at=artifact.created_at,
                )
                for artifact in artifacts
            ),
        )

    def list_projection_events(self, run_id: str) -> tuple[ProjectionEvent, ...]:
        with self._session() as session:
            rows = session.execute(
                select(SqlRunProjectionEvent)
                .where(
                    SqlRunProjectionEvent.workspace_id == current_workspace_id(),
                    SqlRunProjectionEvent.run_id == run_id,
                )
                .order_by(SqlRunProjectionEvent.created_at, SqlRunProjectionEvent.id)
            ).scalars()
            return tuple(
                ProjectionEvent(
                    source=row.source,
                    source_event_id=row.source_event_id,
                    event_type=row.event_type,
                    run_id=row.run_id,
                    task_id=row.task_id,
                    attempt_id=row.attempt_id,
                    session_id=row.session_id,
                    conversation_item_id=row.conversation_item_id,
                    payload=json.loads(row.payload or "{}"),
                )
                for row in rows
            )

    def acquire_worktree_lease(
        self,
        *,
        run_id: str,
        attempt_id: str | None,
        child_session_id: str,
        host_id: str,
        repository_id: str,
        worktree_path: str,
        branch: str,
        owner_id: str,
        base_commit: str | None = None,
    ) -> WorktreeLease:
        row = SqlWorktreeLease(
            id=uuid4().hex,
            run_id=run_id,
            attempt_id=attempt_id,
            child_session_id=child_session_id,
            host_id=host_id,
            repository_id=repository_id,
            worktree_path=worktree_path,
            worktree_path_cksum=worktree_path_cksum(worktree_path),
            branch=branch,
            owner_id=owner_id,
            state=WorktreeLeaseStatus.ACTIVE.value,
            heartbeat_at=now_epoch(),
            base_commit=base_commit,
            output_commit=None,
            created_at=now_epoch(),
            released_at=None,
        )
        try:
            with self._session() as session:
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise ValueError(f"worktree path is already leased: {worktree_path}") from exc
        return _lease(row)

    def list_active_worktree_leases(self, run_id: str) -> tuple[WorktreeLease, ...]:
        with self._session() as session:
            rows = session.execute(
                select(SqlWorktreeLease)
                .where(
                    SqlWorktreeLease.workspace_id == current_workspace_id(),
                    SqlWorktreeLease.run_id == run_id,
                    SqlWorktreeLease.state.in_(
                        (
                            WorktreeLeaseStatus.ACTIVE.value,
                            WorktreeLeaseStatus.RECOVERY_REQUIRED.value,
                        )
                    ),
                )
                .order_by(SqlWorktreeLease.created_at, SqlWorktreeLease.id)
            ).scalars()
            return tuple(_lease(row) for row in rows)

    def list_recoverable_worktree_leases(self) -> tuple[WorktreeLease, ...]:
        """List all active or recovery-required leases in this workspace."""
        with self._session() as session:
            rows = session.execute(
                select(SqlWorktreeLease)
                .where(
                    SqlWorktreeLease.workspace_id == current_workspace_id(),
                    SqlWorktreeLease.state.in_(
                        (
                            WorktreeLeaseStatus.ACTIVE.value,
                            WorktreeLeaseStatus.RECOVERY_REQUIRED.value,
                        )
                    ),
                )
                .order_by(SqlWorktreeLease.created_at, SqlWorktreeLease.id)
            ).scalars()
            return tuple(_lease(row) for row in rows)

    def list_recoverable_worktree_lease_workspace_ids(self) -> tuple[int, ...]:
        """Enumerate tenant IDs containing active recovery work."""
        with self._session() as session:
            rows = session.execute(
                select(SqlWorktreeLease.workspace_id)
                .where(
                    SqlWorktreeLease.state.in_(
                        (
                            WorktreeLeaseStatus.ACTIVE.value,
                            WorktreeLeaseStatus.RECOVERY_REQUIRED.value,
                        )
                    )
                )
                .distinct()
                .order_by(SqlWorktreeLease.workspace_id)
            ).scalars()
            return tuple(int(workspace_id) for workspace_id in rows)

    def mark_worktree_lease_recovery_required(
        self, lease_id: str, *, owner_id: str
    ) -> WorktreeLease:
        """Persist that host cleanup must be retried by lease maintenance."""
        with self._session() as session:
            row = session.get(SqlWorktreeLease, (current_workspace_id(), lease_id))
            if row is None:
                raise ValueError(f"Worktree lease not found: {lease_id}")
            if row.owner_id != owner_id:
                raise ValueError("worktree lease belongs to another owner")
            if row.state != WorktreeLeaseStatus.RELEASED.value:
                row.state = WorktreeLeaseStatus.RECOVERY_REQUIRED.value
            session.flush()
            return _lease(row)

    def release_worktree_lease(
        self, lease_id: str, *, owner_id: str, output_commit: str | None = None
    ) -> WorktreeLease:
        with self._session() as session:
            row = session.get(SqlWorktreeLease, (current_workspace_id(), lease_id))
            if row is None:
                raise ValueError(f"Worktree lease not found: {lease_id}")
            if row.owner_id != owner_id:
                raise ValueError("worktree lease belongs to another owner")
            if row.state != WorktreeLeaseStatus.RELEASED.value:
                row.state = WorktreeLeaseStatus.RELEASED.value
                row.output_commit = output_commit
                row.released_at = now_epoch()
            session.flush()
            return _lease(row)

    def heartbeat_worktree_lease(self, lease_id: str, *, owner_id: str) -> WorktreeLease:
        with self._session() as session:
            row = session.get(SqlWorktreeLease, (current_workspace_id(), lease_id))
            if row is None:
                raise ValueError(f"Worktree lease not found: {lease_id}")
            if row.owner_id != owner_id:
                raise ValueError("worktree lease belongs to another owner")
            if row.state != WorktreeLeaseStatus.ACTIVE.value:
                raise ValueError("only active worktree leases can be heartbeated")
            row.heartbeat_at = now_epoch()
            session.flush()
            return _lease(row)


def _run(row: SqlRun) -> Run:
    if (
        row.agent_id is None
        or row.bundle_version is None
        or row.bundle_digest is None
        or row.bundle_location is None
        or row.workspace_bundle_id is None
        or row.auth_scope is None
        or row.source_event_id is None
    ):
        raise ValueError(f"Run {row.id!r} is not a native Session-backed projection")
    return Run(
        id=row.id,
        actor_id=row.account_id or "local",
        auth_scope=row.auth_scope,
        source=row.source,
        source_event_id=row.source_event_id,
        agent_id=row.agent_id,
        bundle_version=row.bundle_version,
        bundle_digest=row.bundle_digest,
        bundle_location=row.bundle_location,
        workspace_id=row.workspace_bundle_id,
        root_session_id=row.root_session_id,
        status=RunStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _task(row: SqlRunTask) -> Task:
    return Task(
        id=row.id,
        run_id=row.run_id,
        title=row.title,
        status=TaskStatus(row.status),
        root_session_id=row.root_session_id,
        child_session_id=row.child_session_id,
        dispatch_title=row.dispatch_title,
        purpose=row.purpose,
        source_event_id=row.source_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attempt(row: SqlAttempt) -> Attempt:
    return Attempt(
        id=row.id,
        task_id=row.task_id,
        status=AttemptStatus(row.status),
        child_session_id=row.child_session_id,
        worker_name=row.worker_name,
        worker_config_path=row.worker_config_path,
        purpose=row.purpose,
        harness=row.harness,
        model=row.model,
        dispatch_call_id=row.dispatch_call_id,
        response_id=row.response_id,
        turn_id=row.turn_id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        retry_of_attempt_id=row.retry_of_attempt_id,
        source_event_id=row.source_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _lease(row: SqlWorktreeLease) -> WorktreeLease:
    if row.run_id is None:
        raise ValueError(f"Worktree lease {row.id!r} is not attached to a Run")
    return WorktreeLease(
        id=row.id,
        run_id=row.run_id,
        attempt_id=row.attempt_id,
        child_session_id=row.child_session_id,
        host_id=row.host_id,
        repository_id=row.repository_id,
        worktree_path=row.worktree_path,
        branch=row.branch,
        owner_id=row.owner_id,
        status=WorktreeLeaseStatus(row.state),
        heartbeat_at=row.heartbeat_at,
        base_commit=row.base_commit,
        output_commit=row.output_commit,
        created_at=row.created_at,
        released_at=row.released_at,
    )


def _required_payload(event: ProjectionEvent, key: str) -> str:
    value = event.payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{event.event_type} requires payload.{key}")
    return value


def _optional_payload(event: ProjectionEvent, key: str) -> str | None:
    value = event.payload.get(key)
    return value if isinstance(value, str) and value else None


def _recompute_run_status(session: object, run_row: SqlRun, now: int) -> None:
    statuses = tuple(
        session.execute(
            select(SqlRunTask.status).where(
                SqlRunTask.workspace_id == current_workspace_id(),
                SqlRunTask.run_id == run_row.id,
            )
        ).scalars()
    )
    if not statuses:
        return
    if any(status in {TaskStatus.RUNNING.value, TaskStatus.BLOCKED.value} for status in statuses):
        status = RunStatus.RUNNING
    elif any(value == TaskStatus.FAILED.value for value in statuses):
        status = RunStatus.FAILED
    elif all(value == TaskStatus.CANCELLED.value for value in statuses):
        status = RunStatus.CANCELLED
    else:
        status = RunStatus.COMPLETED
    run_row.status = status.value
    run_row.updated_at = now
