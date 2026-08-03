"""Attempt-scoped leases for isolated multi-repository Git worktrees."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from omnigent.server.host_registry import HostConnection, HostRegistry
from omnigent.server.routes._host_worktree import (
    create_worktree_on_host,
    remove_worktree_on_host,
)
from omnigent.workspaces.manifest import WorkspaceRepository


class LeaseStatus(StrEnum):
    """Lifecycle states for an attempt worktree lease."""

    ACTIVE = "active"
    EXPIRED = "expired"
    RECOVERY_REQUIRED = "recovery_required"
    RELEASED = "released"


class WorktreeLeaseError(RuntimeError):
    """Base exception for attempt worktree lease operations."""


class LeaseOwnershipError(WorktreeLeaseError):
    """Raised when a lease owner tries to operate on another owner's lease."""


class LeaseExpiredError(WorktreeLeaseError):
    """Raised when an expired lease must be recovered before it can be reused."""


@dataclass
class WorktreeLease:
    """One repository worktree owned by an execution attempt."""

    host_id: str
    repository_id: str
    repo_path: str
    attempt_id: str
    worktree_path: str
    branch: str
    owner: str
    status: LeaseStatus
    heartbeat_at: float

    @property
    def owner_id(self) -> str:
        """Compatibility spelling for callers that use an ``*_id`` convention."""
        return self.owner


class WorktreeLeaseManager:
    """Create, heartbeat, release, and recover attempt worktree leases.

    The manager owns only server-side lease state. Git operations remain on the
    selected host through the existing worktree tunnel helpers. Locks are keyed
    by host and canonical source repository path, preventing two concurrent
    attempts from asking a host to derive the same worktree directory at once.
    """

    def __init__(
        self, *, ttl_s: float = 300.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        self._ttl_s = ttl_s
        self._clock = clock
        self._records: list[WorktreeLease] = []
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._heartbeat_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    @property
    def records(self) -> tuple[WorktreeLease, ...]:
        """All leases retained for audit and recovery, in acquisition order."""
        return tuple(self._records)

    async def acquire(
        self,
        *,
        host_id: str,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        workspace_root: Path | str,
        repositories: Iterable[WorkspaceRepository],
        attempt_id: str,
        owner_id: str,
        branch_names: Mapping[str, str] | None = None,
    ) -> tuple[WorktreeLease, ...]:
        """Atomically acquire one isolated worktree lease per repository.

        Repeating an active acquisition by the same owner is idempotent. A
        failed multi-repository acquisition removes worktrees already created
        during this call before surfacing the original host error.
        """
        self._require_host(host_id, host_conn)
        repo_entries = self._repository_entries(workspace_root, repositories)
        keys = [(host_id, repo_path) for _, repo_path, _ in repo_entries]
        locks = [self._locks.setdefault(key, asyncio.Lock()) for key in sorted(keys)]
        for lock in locks:
            await lock.acquire()
        try:
            current = self._attempt_leases(host_id, attempt_id, repo_entries)
            if current:
                if len(current) != len(repo_entries):
                    raise WorktreeLeaseError(
                        "attempt already has a different repository worktree lease set"
                    )
                if any(lease.owner != owner_id for lease in current):
                    raise LeaseOwnershipError("attempt worktree lease belongs to another owner")
                if any(lease.status is LeaseStatus.EXPIRED for lease in current):
                    raise LeaseExpiredError(
                        "attempt worktree lease has expired and requires recovery"
                    )
                if all(lease.status is LeaseStatus.ACTIVE for lease in current):
                    self.start_heartbeat(current)
                    return tuple(current)
                raise WorktreeLeaseError("attempt worktree lease was already released")

            created: list[WorktreeLease] = []
            try:
                for repository, repo_path, base_branch in repo_entries:
                    result = await create_worktree_on_host(
                        host_registry=host_registry,
                        host_conn=host_conn,
                        repo_path=repo_path,
                        branch_name=(branch_names or {}).get(
                            repository.id, _branch_name(attempt_id, repository.id)
                        ),
                        base_branch=base_branch,
                    )
                    created.append(
                        WorktreeLease(
                            host_id=host_id,
                            repository_id=repository.id,
                            repo_path=repo_path,
                            attempt_id=attempt_id,
                            worktree_path=result.worktree_path,
                            branch=result.branch,
                            owner=owner_id,
                            status=LeaseStatus.ACTIVE,
                            heartbeat_at=self._clock(),
                        )
                    )
            except Exception:
                failed_cleanup = await self._remove_created(host_registry, host_conn, created)
                for lease in failed_cleanup:
                    lease.status = LeaseStatus.RECOVERY_REQUIRED
                self._records.extend(failed_cleanup)
                raise
            self._records.extend(created)
            self.start_heartbeat(created)
            return tuple(created)
        finally:
            for lock in reversed(locks):
                lock.release()

    def heartbeat(self, leases: Iterable[WorktreeLease], *, owner_id: str) -> None:
        """Refresh active leases after verifying their common owner."""
        records = tuple(leases)
        self._require_owner(records, owner_id)
        if any(lease.status is not LeaseStatus.ACTIVE for lease in records):
            raise LeaseExpiredError("only active attempt worktree leases can be heartbeated")
        now = self._clock()
        for lease in records:
            lease.heartbeat_at = now

    def heartbeat_active(self, *, host_id: str | None = None) -> tuple[WorktreeLease, ...]:
        """Refresh active leases for a trusted process maintenance loop."""
        now = self._clock()
        active = tuple(
            lease
            for lease in self._records
            if lease.status is LeaseStatus.ACTIVE and (host_id is None or lease.host_id == host_id)
        )
        for lease in active:
            lease.heartbeat_at = now
        return active

    def start_heartbeat(self, leases: Iterable[WorktreeLease]) -> None:
        """Start one owner heartbeat task for an active attempt lease set."""
        records = tuple(leases)
        if not records or any(lease.status is not LeaseStatus.ACTIVE for lease in records):
            return
        keys = {(lease.host_id, lease.attempt_id, lease.owner) for lease in records}
        if len(keys) != 1:
            raise WorktreeLeaseError("heartbeat leases must belong to one attempt owner")
        key = next(iter(keys))
        if key in self._heartbeat_tasks:
            return
        self._heartbeat_tasks[key] = asyncio.create_task(
            self._heartbeat_loop(key),
            name=f"worktree-lease-heartbeat-{key[1]}",
        )

    async def stop_heartbeat(self, leases: Iterable[WorktreeLease]) -> None:
        """Stop the owner heartbeat task associated with *leases*."""
        records = tuple(leases)
        keys = {(lease.host_id, lease.attempt_id, lease.owner) for lease in records}
        for key in keys:
            task = self._heartbeat_tasks.pop(key, None)
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _heartbeat_loop(self, key: tuple[str, str, str]) -> None:
        host_id, attempt_id, owner = key
        try:
            while True:
                await asyncio.sleep(max(self._ttl_s / 3, 0.01))
                active = tuple(
                    lease
                    for lease in self._records
                    if lease.host_id == host_id
                    and lease.attempt_id == attempt_id
                    and lease.owner == owner
                    and lease.status is LeaseStatus.ACTIVE
                )
                if not active:
                    return
                self.heartbeat(active, owner_id=owner)
        finally:
            current = asyncio.current_task()
            if self._heartbeat_tasks.get(key) is current:
                self._heartbeat_tasks.pop(key, None)

    async def release(
        self,
        *,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        leases: Iterable[WorktreeLease],
        owner_id: str,
    ) -> None:
        """Owner-checked, idempotently release attempt worktree leases."""
        records = tuple(leases)
        self._require_owner(records, owner_id)
        await self.stop_heartbeat(records)
        await self._release(host_registry, host_conn, records)

    def find(self, *, worktree_path: str, branch: str | None = None) -> WorktreeLease | None:
        """Find a retained lease by its worktree path for session teardown."""
        for lease in reversed(self._records):
            if (
                lease.status is not LeaseStatus.RELEASED
                and lease.worktree_path == worktree_path
                and (branch is None or lease.branch == branch)
            ):
                return lease
        return None

    async def recover_expired(
        self, *, host_registry: HostRegistry, host_conn: HostConnection
    ) -> tuple[WorktreeLease, ...]:
        """Reclaim active leases whose owner stopped heartbeating."""
        now = self._clock()
        candidates = tuple(
            lease
            for lease in self._records
            if lease.host_id == host_conn.host_id
            and lease.status in (LeaseStatus.ACTIVE, LeaseStatus.RECOVERY_REQUIRED)
        )
        locks = self._lease_locks(candidates)
        for lock in locks:
            await lock.acquire()
        try:
            expired = tuple(
                lease
                for lease in candidates
                if lease.status is LeaseStatus.RECOVERY_REQUIRED
                or (lease.status is LeaseStatus.ACTIVE and now - lease.heartbeat_at >= self._ttl_s)
            )
            for lease in expired:
                if lease.status is LeaseStatus.ACTIVE:
                    lease.status = LeaseStatus.EXPIRED
            await self.stop_heartbeat(expired)
            try:
                await self._release_locked(host_registry, host_conn, expired)
            except Exception:
                for lease in expired:
                    if lease.status is not LeaseStatus.RELEASED:
                        lease.status = LeaseStatus.RECOVERY_REQUIRED
                raise
        finally:
            for lock in reversed(locks):
                lock.release()
        return expired

    async def _release(
        self,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        records: tuple[WorktreeLease, ...],
    ) -> None:
        active = tuple(lease for lease in records if lease.status is not LeaseStatus.RELEASED)
        if not active:
            return
        host_ids = {lease.host_id for lease in active}
        if len(host_ids) != 1:
            raise WorktreeLeaseError("leases from multiple hosts must be released separately")
        self._require_host(next(iter(host_ids)), host_conn)
        locks = self._lease_locks(active)
        for lock in locks:
            await lock.acquire()
        try:
            await self._release_locked(host_registry, host_conn, active)
        finally:
            for lock in reversed(locks):
                lock.release()

    def _lease_locks(self, records: Iterable[WorktreeLease]) -> list[asyncio.Lock]:
        return [
            self._locks.setdefault((lease.host_id, lease.repo_path), asyncio.Lock())
            for lease in sorted(records, key=lambda item: (item.host_id, item.repo_path))
        ]

    async def _release_locked(
        self,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        records: Iterable[WorktreeLease],
    ) -> None:
        for lease in reversed(tuple(records)):
            await remove_worktree_on_host(
                host_registry=host_registry,
                host_conn=host_conn,
                worktree_path=lease.worktree_path,
                branch=lease.branch,
                delete_branch=True,
            )
            lease.status = LeaseStatus.RELEASED

    async def _remove_created(
        self,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        created: list[WorktreeLease],
    ) -> list[WorktreeLease]:
        failed: list[WorktreeLease] = []
        for lease in reversed(created):
            # The originating create failure remains the useful error; a later
            # recovery can clean up a host worktree that resisted this removal.
            try:
                await remove_worktree_on_host(
                    host_registry=host_registry,
                    host_conn=host_conn,
                    worktree_path=lease.worktree_path,
                    branch=lease.branch,
                    delete_branch=True,
                )
            except Exception:  # noqa: BLE001 - rollback must preserve orphaned leases
                failed.append(lease)
        return failed

    def _attempt_leases(
        self,
        host_id: str,
        attempt_id: str,
        entries: tuple[tuple[WorkspaceRepository, str, str | None], ...],
    ) -> list[WorktreeLease]:
        keys = {(host_id, repository.id, repo_path) for repository, repo_path, _ in entries}
        return [
            lease
            for lease in self._records
            if (lease.host_id, lease.repository_id, lease.repo_path) in keys
            and lease.attempt_id == attempt_id
        ]

    @staticmethod
    def _repository_entries(
        workspace_root: Path | str, repositories: Iterable[WorkspaceRepository]
    ) -> tuple[tuple[WorkspaceRepository, str, str | None], ...]:
        root = Path(workspace_root).resolve()
        entries = tuple(
            (repository, str((root / repository.path).resolve()), repository.default_branch)
            for repository in repositories
        )
        ids = [repository.id for repository, _, _ in entries]
        paths = [repo_path for _, repo_path, _ in entries]
        if not entries:
            raise ValueError("at least one repository is required")
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("repositories must have unique ids and paths")
        return tuple(sorted(entries, key=lambda entry: entry[0].id))

    @staticmethod
    def _require_host(host_id: str, host_conn: HostConnection) -> None:
        if host_conn.host_id != host_id:
            raise WorktreeLeaseError("host connection does not own this worktree lease")

    @staticmethod
    def _require_owner(records: tuple[WorktreeLease, ...], owner_id: str) -> None:
        if any(lease.owner != owner_id for lease in records):
            raise LeaseOwnershipError("attempt worktree lease belongs to another owner")


def _branch_name(attempt_id: str, repository_id: str) -> str:
    """Return a valid, stable branch name unique to an attempt/repository."""
    attempt = hashlib.sha256(attempt_id.encode()).hexdigest()[:16]
    repository = hashlib.sha256(repository_id.encode()).hexdigest()[:16]
    return f"omnigent/attempt-{attempt}/repo-{repository}"
