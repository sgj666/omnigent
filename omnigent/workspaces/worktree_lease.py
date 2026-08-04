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
from typing import Any

from omnigent.db.db_models import current_workspace_id, workspace_scope
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
    durable_lease_id: str | None = None
    run_id: str | None = None
    child_session_id: str | None = None
    workspace_id: int = 0

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
        self,
        *,
        ttl_s: float = 300.0,
        startup_grace_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        durable_store: Any | None = None,
    ) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        if startup_grace_s < 0:
            raise ValueError("startup_grace_s must be non-negative")
        self._ttl_s = ttl_s
        self._startup_grace_s = startup_grace_s
        self._clock = clock
        self._durable_store = durable_store
        self._records: list[WorktreeLease] = []
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._heartbeat_tasks: dict[tuple[int, str, str, str], asyncio.Task[None]] = {}
        self._hydrated_active_attempts: set[tuple[int, str]] = set()
        self._hydrated_active_deadlines: dict[tuple[int, str], float] = {}
        self._hydrate_durable_records()

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
        run_id: str | None = None,
        child_session_id: str | None = None,
        branch_names: Mapping[str, str] | None = None,
        target_paths: Mapping[str, str] | None = None,
    ) -> tuple[WorktreeLease, ...]:
        """Atomically acquire one isolated worktree lease per repository.

        Repeating an active acquisition by the same owner is idempotent. A
        failed multi-repository acquisition removes worktrees already created
        during this call before surfacing the original host error.
        """
        self._require_host(host_id, host_conn)
        durable_context = (
            self._durable_store is not None and run_id is not None and child_session_id is not None
        )
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
                    expected_target = (target_paths or {}).get(repository.id)
                    result = await create_worktree_on_host(
                        host_registry=host_registry,
                        host_conn=host_conn,
                        repo_path=repo_path,
                        branch_name=(branch_names or {}).get(
                            repository.id, _branch_name(attempt_id, repository.id)
                        ),
                        base_branch=base_branch,
                        target_path=expected_target,
                    )
                    lease = WorktreeLease(
                        host_id=host_id,
                        repository_id=repository.id,
                        repo_path=repo_path,
                        attempt_id=attempt_id,
                        worktree_path=result.worktree_path,
                        branch=result.branch,
                        owner=owner_id,
                        status=LeaseStatus.ACTIVE,
                        heartbeat_at=self._clock(),
                        run_id=run_id,
                        child_session_id=child_session_id,
                        workspace_id=current_workspace_id(),
                    )
                    created.append(lease)
                    if durable_context:
                        durable = self._durable_store.acquire_worktree_lease(
                            run_id=run_id,
                            attempt_id=attempt_id,
                            child_session_id=child_session_id,
                            host_id=host_id,
                            repository_id=repository.id,
                            worktree_path=result.worktree_path,
                            branch=result.branch,
                            owner_id=owner_id,
                        )
                        lease.durable_lease_id = durable.id
                    if (
                        expected_target is not None
                        and Path(result.worktree_path).resolve() != Path(expected_target).resolve()
                    ):
                        raise WorktreeLeaseError(
                            "host created the worktree outside the reserved attempt path"
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
            if self._durable_store is not None and lease.durable_lease_id is not None:
                with workspace_scope(lease.workspace_id):
                    self._durable_store.heartbeat_worktree_lease(
                        lease.durable_lease_id,
                        owner_id=owner_id,
                    )

    def heartbeat_active(self, *, host_id: str | None = None) -> tuple[WorktreeLease, ...]:
        """Refresh active leases for a trusted process maintenance loop."""
        now = self._clock()
        active = tuple(
            lease
            for lease in self._records
            if lease.status is LeaseStatus.ACTIVE
            and lease.workspace_id == current_workspace_id()
            and (host_id is None or lease.host_id == host_id)
        )
        for lease in active:
            lease.heartbeat_at = now
        return active

    def start_heartbeat(self, leases: Iterable[WorktreeLease]) -> None:
        """Start one owner heartbeat task for an active attempt lease set."""
        records = tuple(leases)
        if not records or any(lease.status is not LeaseStatus.ACTIVE for lease in records):
            return
        keys = {
            (lease.workspace_id, lease.host_id, lease.attempt_id, lease.owner)
            for lease in records
        }
        if len(keys) != 1:
            raise WorktreeLeaseError("heartbeat leases must belong to one attempt owner")
        key = next(iter(keys))
        if key in self._heartbeat_tasks:
            return
        self._heartbeat_tasks[key] = asyncio.create_task(
            self._heartbeat_loop(key),
            name=f"worktree-lease-heartbeat-{key[2]}",
        )

    async def stop_heartbeat(self, leases: Iterable[WorktreeLease]) -> None:
        """Stop the owner heartbeat task associated with *leases*."""
        records = tuple(leases)
        keys = {
            (lease.workspace_id, lease.host_id, lease.attempt_id, lease.owner)
            for lease in records
        }
        for key in keys:
            task = self._heartbeat_tasks.pop(key, None)
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _heartbeat_loop(self, key: tuple[int, str, str, str]) -> None:
        workspace_id, host_id, attempt_id, owner = key
        try:
            while True:
                await asyncio.sleep(max(self._ttl_s / 3, 0.01))
                active = tuple(
                    lease
                    for lease in self._records
                    if lease.host_id == host_id
                    and lease.workspace_id == workspace_id
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

    async def defer_recovery(self, leases: Iterable[WorktreeLease]) -> None:
        """Stop owner heartbeats and persist cleanup for a disconnected host."""
        records = tuple(leases)
        await self.stop_heartbeat(records)
        for lease in records:
            if lease.status is not LeaseStatus.RELEASED:
                lease.status = LeaseStatus.RECOVERY_REQUIRED
                self._mark_recovery_required(lease)

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

    def for_child(self, child_session_id: str) -> tuple[WorktreeLease, ...]:
        """Return unreleased multi-repository leases owned by one Child."""
        return tuple(
            lease
            for lease in self._records
            if lease.child_session_id == child_session_id
            and lease.workspace_id == current_workspace_id()
            and lease.status is not LeaseStatus.RELEASED
        )

    def for_attempt(self, attempt_id: str) -> tuple[WorktreeLease, ...]:
        """Return every unreleased repository lease for one Attempt."""
        return tuple(
            lease
            for lease in self._records
            if lease.attempt_id == attempt_id
            and lease.workspace_id == current_workspace_id()
            and lease.status is not LeaseStatus.RELEASED
        )

    def recovery_candidate_attempt_ids(self, host_id: str) -> set[str]:
        """Return attempts eligible for cleanup, excluding restart-grace leases."""
        now = self._clock()
        return {
            lease.attempt_id
            for lease in self._records
            if lease.host_id == host_id
            and lease.workspace_id == current_workspace_id()
            and (lease.workspace_id, lease.attempt_id) not in self._hydrated_active_attempts
            and (
                lease.status is LeaseStatus.RECOVERY_REQUIRED
                or (
                    lease.status is LeaseStatus.ACTIVE
                    and now - lease.heartbeat_at >= self._ttl_s
                )
            )
        }

    def recovery_should_delete_child(self, attempt_id: str) -> bool:
        """Return whether recovery is cleaning an initial Child Attempt."""
        if self._durable_store is None:
            return False
        attempt = self._durable_store.get_attempt(attempt_id)
        return attempt is not None and attempt.retry_of_attempt_id is None

    async def reconcile_hydrated_active(
        self,
        *,
        host_registry: Any,
        conversation_store: Any,
        liveness_lookup: Callable[[list[str]], Mapping[str, Any]],
    ) -> None:
        """Verify hydrated ACTIVE attempts before recovery can expire them."""
        workspace_id = current_workspace_id()
        attempt_ids = tuple(
            sorted(
                attempt_id
                for candidate_workspace_id, attempt_id in self._hydrated_active_attempts
                if candidate_workspace_id == workspace_id
            )
        )
        if not attempt_ids:
            return
        child_ids = sorted(
            {
                lease.child_session_id
                for attempt_id in attempt_ids
                for lease in self.for_attempt(attempt_id)
                if lease.child_session_id is not None
            }
        )
        try:
            liveness = liveness_lookup(child_ids)
        except Exception:  # noqa: BLE001 - an unverifiable restart is recovered
            liveness = {}
        for attempt_id in attempt_ids:
            leases = self.for_attempt(attempt_id)
            if not leases:
                self._hydrated_active_attempts.discard((workspace_id, attempt_id))
                self._hydrated_active_deadlines.pop((workspace_id, attempt_id), None)
                continue
            child_id = leases[0].child_session_id
            run_id = leases[0].run_id
            child = (
                conversation_store.get_conversation(child_id)
                if isinstance(child_id, str)
                else None
            )
            latest = (
                self._durable_store.get_latest_attempt_for_child(run_id, child_id)
                if self._durable_store is not None
                and isinstance(run_id, str)
                and isinstance(child_id, str)
                else None
            )
            latest_attempt = latest[1] if latest is not None else None
            latest_status = getattr(getattr(latest_attempt, "status", None), "value", None)
            state = liveness.get(child_id) if isinstance(child_id, str) else None
            verified_live = (
                child is not None
                and getattr(latest_attempt, "id", None) == attempt_id
                and latest_status in {"queued", "running"}
                and state is not None
                and getattr(state, "runner_online", False) is True
                and getattr(state, "host_online", False) is True
                and host_registry.get(leases[0].host_id) is not None
            )
            if verified_live:
                self.heartbeat(leases, owner_id=leases[0].owner)
                self.start_heartbeat(leases)
                self._hydrated_active_attempts.discard((workspace_id, attempt_id))
                self._hydrated_active_deadlines.pop((workspace_id, attempt_id), None)
                continue
            durable_active = (
                child is not None
                and getattr(latest_attempt, "id", None) == attempt_id
                and latest_status in {"queued", "running"}
            )
            deadline = self._hydrated_active_deadlines.get(
                (workspace_id, attempt_id), self._clock()
            )
            if durable_active and self._clock() < deadline:
                continue
            await self.defer_recovery(leases)
            self._hydrated_active_attempts.discard((workspace_id, attempt_id))
            self._hydrated_active_deadlines.pop((workspace_id, attempt_id), None)

    async def recover_expired(
        self,
        *,
        host_registry: HostRegistry,
        host_conn: HostConnection,
        safe_attempt_ids: set[str] | None = None,
    ) -> tuple[WorktreeLease, ...]:
        """Reclaim active leases whose owner stopped heartbeating."""
        now = self._clock()
        candidates = tuple(
            lease
            for lease in self._records
            if lease.host_id == host_conn.host_id
            and lease.workspace_id == current_workspace_id()
            and lease.status in (LeaseStatus.ACTIVE, LeaseStatus.RECOVERY_REQUIRED)
            and (safe_attempt_ids is None or lease.attempt_id in safe_attempt_ids)
            and not (
                lease.status is LeaseStatus.ACTIVE
                and (lease.workspace_id, lease.attempt_id)
                in self._hydrated_active_attempts
            )
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
                        self._mark_recovery_required(lease)
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
        except Exception:
            for lease in active:
                if lease.status is not LeaseStatus.RELEASED:
                    lease.status = LeaseStatus.RECOVERY_REQUIRED
                    self._mark_recovery_required(lease)
            raise
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
            if self._durable_store is not None and lease.durable_lease_id is not None:
                with workspace_scope(lease.workspace_id):
                    self._durable_store.release_worktree_lease(
                        lease.durable_lease_id,
                        owner_id=lease.owner,
                    )

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
                if self._durable_store is not None and lease.durable_lease_id is not None:
                    with workspace_scope(lease.workspace_id):
                        self._durable_store.release_worktree_lease(
                            lease.durable_lease_id,
                            owner_id=lease.owner,
                        )
            except Exception:  # noqa: BLE001 - rollback must preserve orphaned leases
                self._mark_recovery_required(lease)
                failed.append(lease)
        return failed

    def _hydrate_durable_records(self) -> None:
        """Restore recoverable leases so the existing maintenance loop sees them."""
        if self._durable_store is None:
            return
        list_recoverable = getattr(self._durable_store, "list_recoverable_worktree_leases", None)
        if not callable(list_recoverable):
            return
        list_workspace_ids = getattr(
            self._durable_store,
            "list_recoverable_worktree_lease_workspace_ids",
            None,
        )
        workspace_ids = list_workspace_ids() if callable(list_workspace_ids) else (0,)
        for workspace_id in workspace_ids:
            with workspace_scope(workspace_id):
                durable_records = list_recoverable()
            for durable in durable_records:
                self._hydrate_durable_record(durable, workspace_id=workspace_id)

    def _hydrate_durable_record(self, durable: Any, *, workspace_id: int) -> None:
        """Restore one durable record under its tenant identity."""
        with workspace_scope(workspace_id):
            attempt_id = getattr(durable, "attempt_id", None)
            run_id = getattr(durable, "run_id", None)
            if not isinstance(attempt_id, str) or not attempt_id or not isinstance(run_id, str):
                return
            run = self._durable_store.get_run(run_id)
            workspace = (
                self._durable_store.get_workspace(run.workspace_id) if run is not None else None
            )
            if workspace is None:
                return
            repository = next(
                (
                    candidate
                    for candidate in workspace.repositories
                    if candidate.id == durable.repository_id
                ),
                None,
            )
            if repository is None:
                return
            status = LeaseStatus(str(durable.status))
            heartbeat_age = max(0.0, time.time() - float(durable.heartbeat_at))
            self._records.append(
                WorktreeLease(
                    host_id=durable.host_id,
                    repository_id=durable.repository_id,
                    repo_path=str((Path(workspace.root_path) / repository.path).resolve()),
                    attempt_id=attempt_id,
                    worktree_path=durable.worktree_path,
                    branch=durable.branch,
                    owner=durable.owner_id,
                    status=status,
                    heartbeat_at=self._clock() - heartbeat_age,
                    durable_lease_id=durable.id,
                    run_id=run_id,
                    child_session_id=durable.child_session_id,
                    workspace_id=workspace_id,
                )
            )
            if status is LeaseStatus.ACTIVE:
                key = (workspace_id, attempt_id)
                self._hydrated_active_attempts.add(key)
                self._hydrated_active_deadlines.setdefault(
                    key,
                    self._clock() + self._startup_grace_s,
                )

    def _mark_recovery_required(self, lease: WorktreeLease) -> None:
        if self._durable_store is None or lease.durable_lease_id is None:
            return
        with workspace_scope(lease.workspace_id):
            self._durable_store.mark_worktree_lease_recovery_required(
                lease.durable_lease_id,
                owner_id=lease.owner,
            )

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
            and lease.workspace_id == current_workspace_id()
        ]

    @staticmethod
    def _repository_entries(
        workspace_root: Path | str, repositories: Iterable[WorkspaceRepository]
    ) -> tuple[tuple[WorkspaceRepository, str, str | None], ...]:
        root = Path(workspace_root).resolve()
        entries_list: list[tuple[WorkspaceRepository, str, str | None]] = []
        for repository in repositories:
            repo_path = (root / repository.path).resolve()
            if repo_path == root or not repo_path.is_relative_to(root):
                raise ValueError("repository path must be a strict child of workspace_root")
            entries_list.append((repository, str(repo_path), repository.default_branch))
        entries = tuple(entries_list)
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
