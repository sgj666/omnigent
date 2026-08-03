"""Tests for attempt-scoped worktree leases across workspace repositories."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from omnigent.workspaces.manifest import WorkspaceRepository
from omnigent.workspaces.worktree_lease import (
    LeaseOwnershipError,
    LeaseStatus,
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
