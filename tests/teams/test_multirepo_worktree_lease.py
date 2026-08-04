"""Tests for attempt-scoped worktree leases across workspace repositories."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnigent.server.routes import _host_worktree
from omnigent.server.routes._sessions.helpers import (
    _create_session_worktree,
    _remove_session_worktree_best_effort,
)
from omnigent.server.schemas import SessionCreateRequest, SessionGitOptions
from omnigent.workspaces.manifest import WorkspaceRepository
from omnigent.workspaces.worktree_lease import (
    LeaseOwnershipError,
    LeaseStatus,
    WorktreeLease,
    WorktreeLeaseManager,
)


@dataclass
class _Created:
    worktree_path: str
    branch: str


class _Host:
    host_id = "host-1"


@pytest.mark.asyncio
async def test_parallel_attempts_on_one_repo_receive_isolated_leases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same source repository is never created concurrently or reused."""
    entered = 0
    most_entered = 0

    async def create(**kwargs: object) -> _Created:
        nonlocal entered, most_entered
        entered += 1
        most_entered = max(most_entered, entered)
        await asyncio.sleep(0)
        entered -= 1
        branch = str(kwargs["branch_name"])
        return _Created(worktree_path=f"/leases/{branch}", branch=branch)

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    manager = WorktreeLeaseManager(ttl_s=60)
    repository = WorkspaceRepository(id="api", path="api")

    first, second = await asyncio.gather(
        manager.acquire(
            host_id="host-1",
            host_registry=object(),
            host_conn=_Host(),
            workspace_root=tmp_path,
            repositories=(repository,),
            attempt_id="attempt-1",
            owner_id="runner-1",
        ),
        manager.acquire(
            host_id="host-1",
            host_registry=object(),
            host_conn=_Host(),
            workspace_root=tmp_path,
            repositories=(repository,),
            attempt_id="attempt-2",
            owner_id="runner-2",
        ),
    )

    assert most_entered == 1
    assert first[0].worktree_path != second[0].worktree_path
    assert first[0].branch != second[0].branch
    assert [
        (lease.host_id, lease.repository_id, lease.attempt_id) for lease in manager.records
    ] == [
        ("host-1", "api", "attempt-1"),
        ("host-1", "api", "attempt-2"),
    ]


@pytest.mark.asyncio
async def test_multi_repo_lease_releases_only_for_its_owner_and_recovers_expired_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each repository gets a lease, and expired paths can be recovered safely."""
    created: list[_Created] = []
    removed: list[tuple[str, str | None]] = []

    async def create(**kwargs: object) -> _Created:
        branch = str(kwargs["branch_name"])
        lease = _Created(worktree_path=f"/leases/{branch}", branch=branch)
        created.append(lease)
        return lease

    async def remove(**kwargs: object) -> None:
        removed.append((str(kwargs["worktree_path"]), kwargs["branch"]))

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    now = 1_000.0
    manager = WorktreeLeaseManager(ttl_s=10, clock=lambda: now)
    repositories = (
        WorkspaceRepository(id="api", path="api", default_branch="main"),
        WorkspaceRepository(id="web", path="web"),
    )

    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=_Host(),
        workspace_root=tmp_path,
        repositories=repositories,
        attempt_id="attempt-1",
        owner_id="runner-1",
    )

    assert [lease.repository_id for lease in leases] == ["api", "web"]
    assert len({lease.worktree_path for lease in leases}) == 2
    assert len({lease.branch for lease in leases}) == 2
    assert all(lease.status is LeaseStatus.ACTIVE for lease in leases)

    with pytest.raises(LeaseOwnershipError):
        await manager.release(
            host_registry=object(), host_conn=_Host(), leases=leases, owner_id="runner-2"
        )
    assert not removed

    now += 11
    recovered = await manager.recover_expired(host_registry=object(), host_conn=_Host())

    assert recovered == leases
    assert removed == [(lease.worktree_path, lease.branch) for lease in reversed(leases)]
    assert all(lease.status is LeaseStatus.RELEASED for lease in leases)
    await manager.release(
        host_registry=object(), host_conn=_Host(), leases=leases, owner_id="runner-1"
    )
    assert len(removed) == len(leases)


def test_host_worktree_exposes_production_lease_manager_factory() -> None:
    """Session/scheduler code has one shared lifecycle service seam."""
    first = _host_worktree.get_attempt_worktree_lease_manager()
    second = _host_worktree.get_attempt_worktree_lease_manager()

    assert first is second
    assert isinstance(first, WorktreeLeaseManager)


@pytest.mark.asyncio
async def test_failed_rollback_retains_unremoved_worktree_for_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cleanup failure remains visible instead of becoming an orphan."""
    removed_attempts = 0
    created_attempts = 0

    async def create(**kwargs: object) -> _Created:
        nonlocal created_attempts
        created_attempts += 1
        if created_attempts == 2:
            raise RuntimeError("second repository failed")
        return _Created(worktree_path="/leases/first", branch="first")

    async def remove(**kwargs: object) -> None:
        nonlocal removed_attempts
        removed_attempts += 1
        if removed_attempts == 1:
            raise RuntimeError("host unavailable during rollback")

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    manager = WorktreeLeaseManager(ttl_s=60)
    repositories = (
        WorkspaceRepository(id="api", path="api"),
        WorkspaceRepository(id="web", path="web"),
    )

    with pytest.raises(RuntimeError, match="second repository failed"):
        await manager.acquire(
            host_id="host-1",
            host_registry=object(),
            host_conn=_Host(),
            workspace_root=tmp_path,
            repositories=repositories,
            attempt_id="attempt-rollback",
            owner_id="runner-1",
        )

    assert len(manager.records) == 1
    assert manager.records[0].status.value == "recovery_required"
    await manager.recover_expired(host_registry=object(), host_conn=_Host())
    assert manager.records[0].status is LeaseStatus.RELEASED


@pytest.mark.asyncio
async def test_recovery_required_waits_for_runner_stop_or_authoritative_absence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created = _Created(worktree_path="/leases/recovery", branch="attempt-recovery")
    removed: list[str] = []
    runner_status = "alive"
    stop_calls: list[str] = []

    async def create(**kwargs: object) -> _Created:
        return created

    async def remove(**kwargs: object) -> None:
        removed.append(str(kwargs["worktree_path"]))

    async def query_status(*args: object, **kwargs: object) -> str:
        return runner_status

    async def stop_runner(
        session_id: str,
        host_id: str,
        runner_id: str,
        host_registry: object,
    ) -> bool:
        del session_id, host_id, host_registry
        stop_calls.append(runner_id)
        return False

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    monkeypatch.setattr(
        "omnigent.server.routes._sessions.helpers._query_host_runner_status",
        query_status,
    )
    monkeypatch.setattr(
        "omnigent.server.routes._sessions.helpers._stop_session_host_runner",
        stop_runner,
    )
    manager = WorktreeLeaseManager(ttl_s=60)
    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=_Host(),
        workspace_root=tmp_path,
        repositories=(WorkspaceRepository(id="api", path="api"),),
        attempt_id="attempt-recovery",
        owner_id="runner-1",
        child_session_id="child-1",
    )
    await manager.defer_recovery(leases)
    registry = SimpleNamespace(get=lambda host_id: _Host())
    conversations = SimpleNamespace(
        get_conversation=lambda child_id: SimpleNamespace(
            id=child_id,
            runner_id="runner-1",
            workspace=str(tmp_path),
            host_id="host-1",
        ),
        claim_host_runner_recovery=lambda *args, **kwargs: True,
    )

    safe = await _host_worktree._confirm_recovery_attempts_stopped(
        manager=manager,
        host_registry=registry,
        host_conn=_Host(),
        conversation_store=conversations,
    )
    recovered = await manager.recover_expired(
        host_registry=registry,
        host_conn=_Host(),
        safe_attempt_ids=set(safe),
    )

    assert safe == {}
    assert recovered == ()
    assert stop_calls == ["runner-1"]
    assert removed == []
    assert leases[0].status is LeaseStatus.RECOVERY_REQUIRED
    assert manager._heartbeat_tasks == {}

    runner_status = "dead"
    safe = await _host_worktree._confirm_recovery_attempts_stopped(
        manager=manager,
        host_registry=registry,
        host_conn=_Host(),
        conversation_store=conversations,
    )
    recovered = await manager.recover_expired(
        host_registry=registry,
        host_conn=_Host(),
        safe_attempt_ids=set(safe),
    )

    assert safe == {"attempt-recovery": "runner-1"}
    assert recovered == leases
    assert removed == [created.worktree_path]
    assert leases[0].status is LeaseStatus.RELEASED


@pytest.mark.asyncio
async def test_expiry_recovery_does_not_remove_lease_released_while_waiting_for_repo_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Expiry transition is serialized with an in-flight owner release."""
    remove_started = asyncio.Event()
    allow_remove = asyncio.Event()

    async def create(**kwargs: object) -> _Created:
        return _Created(worktree_path="/leases/api", branch="attempt-branch")

    async def remove(**kwargs: object) -> None:
        remove_started.set()
        await allow_remove.wait()

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    now = 1_000.0
    manager = WorktreeLeaseManager(ttl_s=10, clock=lambda: now)
    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=_Host(),
        workspace_root=tmp_path,
        repositories=(WorkspaceRepository(id="api", path="api"),),
        attempt_id="attempt-race",
        owner_id="runner-1",
    )
    now += 11

    release_task = asyncio.create_task(
        manager.release(
            host_registry=object(), host_conn=_Host(), leases=leases, owner_id="runner-1"
        )
    )
    await remove_started.wait()
    recovery_task = asyncio.create_task(
        manager.recover_expired(host_registry=object(), host_conn=_Host())
    )
    await asyncio.sleep(0)
    allow_remove.set()

    await release_task
    assert await recovery_task == ()
    assert leases[0].status is LeaseStatus.RELEASED


@pytest.mark.asyncio
async def test_failed_expired_removal_remains_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient host failure does not strand a lease in EXPIRED."""
    remove_attempts = 0

    async def create(**kwargs: object) -> _Created:
        return _Created(worktree_path="/leases/api", branch="attempt-branch")

    async def remove(**kwargs: object) -> None:
        nonlocal remove_attempts
        remove_attempts += 1
        if remove_attempts == 1:
            raise RuntimeError("host temporarily unavailable")

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    now = 1_000.0
    manager = WorktreeLeaseManager(ttl_s=10, clock=lambda: now)
    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=_Host(),
        workspace_root=tmp_path,
        repositories=(WorkspaceRepository(id="api", path="api"),),
        attempt_id="attempt-retry",
        owner_id="runner-1",
    )
    now += 11

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await manager.recover_expired(host_registry=object(), host_conn=_Host())

    assert leases[0].status is LeaseStatus.RECOVERY_REQUIRED
    assert await manager.recover_expired(host_registry=object(), host_conn=_Host()) == leases
    assert leases[0].status is LeaseStatus.RELEASED


@pytest.mark.asyncio
async def test_session_worktree_helpers_use_lease_lifecycle_for_attempt_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real session helper acquires and releases an attempt lease."""
    lease = WorktreeLease(
        host_id="host-1",
        repository_id="session-repository",
        repo_path="/repos/api",
        attempt_id="attempt-1",
        worktree_path="/leases/api",
        branch="feature/task",
        owner="runner-1",
        status=LeaseStatus.ACTIVE,
        heartbeat_at=1_000.0,
    )
    acquired: dict[str, object] = {}
    heartbeated: dict[str, object] = {}
    released: dict[str, object] = {}

    async def acquire(**kwargs: object) -> tuple[WorktreeLease, ...]:
        acquired.update(kwargs)
        return (lease,)

    async def release(**kwargs: object) -> None:
        released.update(kwargs)

    def heartbeat(leases: object, *, owner_id: str) -> None:
        heartbeated["leases"] = leases
        heartbeated["owner_id"] = owner_id

    monkeypatch.setattr(_host_worktree, "acquire_attempt_worktree_leases", acquire)
    monkeypatch.setattr(_host_worktree, "heartbeat_attempt_worktree_leases", heartbeat)
    monkeypatch.setattr(_host_worktree, "release_attempt_worktree_leases", release)
    registry = SimpleNamespace(get=lambda host_id: _Host())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(host_registry=registry)))

    created = await _create_session_worktree(
        host_id="host-1",
        source_repo="/repos/api",
        git=SessionGitOptions(branch_name="feature/task"),
        request=request,
        attempt_id="attempt-1",
        lease_owner_id="runner-1",
    )
    await _remove_session_worktree_best_effort(
        host_id="host-1",
        worktree_path=created.worktree_path,
        branch=created.branch,
        delete_branch=True,
        request=request,
        reason="attempt-finished",
        lease=created.lease,
    )

    assert acquired["attempt_id"] == "attempt-1"
    assert acquired["owner_id"] == "runner-1"
    assert acquired["branch_names"] == {"session-repository": "feature/task"}
    assert heartbeated == {"leases": (lease,), "owner_id": "runner-1"}
    assert released["leases"] == (lease,)
    assert released["owner_id"] == "runner-1"


def test_session_create_request_validates_optional_attempt_context() -> None:
    """Attempt context is accepted only as a complete pair with Git mode."""
    body = SessionCreateRequest(
        agent_id="agent-1",
        host_id="host-1",
        workspace="/repos/api",
        git=SessionGitOptions(branch_name="feature/task"),
        attempt_id="attempt-1",
        lease_owner_id="runner-1",
    )

    assert body.attempt_id == "attempt-1"
    assert body.lease_owner_id == "runner-1"

    with pytest.raises(ValueError, match="must be provided together"):
        SessionCreateRequest(
            agent_id="agent-1",
            host_id="host-1",
            workspace="/repos/api",
            git=SessionGitOptions(branch_name="feature/task"),
            attempt_id="attempt-1",
        )


@pytest.mark.asyncio
async def test_lease_maintenance_recovers_without_blind_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The maintenance loop recovers; live owners heartbeat explicitly."""
    from omnigent.server.routes._host_worktree import maintain_attempt_worktree_leases

    stop = asyncio.Event()
    lease = WorktreeLease(
        host_id="host-1",
        repository_id="api",
        repo_path="/repos/api",
        attempt_id="attempt-1",
        worktree_path="/leases/api",
        branch="feature/task",
        owner="runner-1",
        status=LeaseStatus.ACTIVE,
        heartbeat_at=1_000.0,
    )
    recovered: list[str] = []
    heartbeated: list[str | None] = []

    class _Manager:
        records = (lease,)

    async def recover(**kwargs: object) -> tuple[WorktreeLease, ...]:
        recovered.append(str(kwargs["host_conn"].host_id))
        stop.set()
        return ()

    monkeypatch.setattr(_host_worktree, "_attempt_worktree_lease_manager", _Manager())
    monkeypatch.setattr(_host_worktree, "recover_expired_attempt_worktree_leases", recover)
    registry = SimpleNamespace(get=lambda host_id: _Host())

    await maintain_attempt_worktree_leases(registry, stop, interval_s=60)

    assert recovered == ["host-1"]
    assert heartbeated == []


@pytest.mark.asyncio
async def test_live_attempt_heartbeat_survives_beyond_lease_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An acquired attempt is renewed by its owner task until release."""

    async def create(**kwargs: object) -> _Created:
        return _Created(worktree_path="/leases/live", branch="attempt-live")

    async def remove(**kwargs: object) -> None:
        return None

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.create_worktree_on_host", create)
    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    manager = WorktreeLeaseManager(ttl_s=0.03)
    leases = await manager.acquire(
        host_id="host-1",
        host_registry=object(),
        host_conn=_Host(),
        workspace_root=tmp_path,
        repositories=(WorkspaceRepository(id="api", path="api"),),
        attempt_id="attempt-live",
        owner_id="runner-live",
    )
    initial_heartbeat = leases[0].heartbeat_at

    await asyncio.sleep(0.08)

    assert leases[0].status is LeaseStatus.ACTIVE
    assert leases[0].heartbeat_at > initial_heartbeat
    await manager.release(
        host_registry=object(), host_conn=_Host(), leases=leases, owner_id="runner-live"
    )
    assert not manager._heartbeat_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_stop_confirmed", [None, False])
async def test_attempt_teardown_requires_confirmed_runner_stop_before_removal(
    monkeypatch: pytest.MonkeyPatch,
    runner_stop_confirmed: bool | None,
) -> None:
    removed: list[str] = []

    async def remove(**kwargs: object) -> None:
        removed.append(str(kwargs["worktree_path"]))

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    manager = WorktreeLeaseManager(ttl_s=60)
    lease = WorktreeLease(
        host_id="host-1",
        repository_id="session-repository",
        repo_path="/repos/api",
        attempt_id="attempt-stop-proof",
        worktree_path="/leases/stop-proof",
        branch="feature/stop-proof",
        owner="runner-stop-proof",
        status=LeaseStatus.ACTIVE,
        heartbeat_at=1_000.0,
    )
    manager._records.append(lease)
    monkeypatch.setattr(_host_worktree, "_attempt_worktree_lease_manager", manager)
    registry = SimpleNamespace(get=lambda _: _Host())

    await _host_worktree.teardown_attempt_worktree_leases_for_attempt(
        host_registry=registry,
        attempt_id=lease.attempt_id,
        runner_stop_confirmed=runner_stop_confirmed,
    )

    assert lease.status is LeaseStatus.RECOVERY_REQUIRED
    assert removed == []

    await _host_worktree.teardown_attempt_worktree_leases_for_attempt(
        host_registry=registry,
        attempt_id=lease.attempt_id,
        runner_stop_confirmed=True,
    )

    assert lease.status is LeaseStatus.RELEASED
    assert removed == [lease.worktree_path]


@pytest.mark.asyncio
async def test_session_cleanup_finds_and_releases_retained_attempt_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session teardown releases a lease even when metadata is not passed."""

    async def remove(**kwargs: object) -> None:
        return None

    monkeypatch.setattr("omnigent.workspaces.worktree_lease.remove_worktree_on_host", remove)
    manager = WorktreeLeaseManager(ttl_s=60)
    lease = WorktreeLease(
        host_id="host-1",
        repository_id="session-repository",
        repo_path="/repos/api",
        attempt_id="attempt-finished",
        worktree_path="/leases/finished",
        branch="feature/finished",
        owner="runner-finished",
        status=LeaseStatus.ACTIVE,
        heartbeat_at=1_000.0,
    )
    manager._records.append(lease)
    monkeypatch.setattr(_host_worktree, "_attempt_worktree_lease_manager", manager)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(host_registry=SimpleNamespace(get=lambda _: _Host()))
        )
    )

    await _remove_session_worktree_best_effort(
        host_id="host-1",
        worktree_path=lease.worktree_path,
        branch=lease.branch,
        delete_branch=True,
        request=request,
        reason="attempt-finished",
    )

    assert lease.status is LeaseStatus.RELEASED
