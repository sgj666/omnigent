"""
Server-side proxies for the host git-worktree tunnel frames.

Like ``_workspace_validation._ask_host_stat``: enqueue a
``host.create_worktree`` / ``host.remove_worktree`` frame, register a
future on the host connection, and await the result with a timeout. The
host (not the server) runs git. See designs/SESSION_GIT_WORKTREE.md.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.host.frames import (
    HostCreateWorktreeFrame,
    HostListWorktreesFrame,
    HostRemoveWorktreeFrame,
    encode_host_frame,
)
from omnigent.server.host_registry import HostConnection, HostRegistry
from omnigent.workspaces.manifest import WorkspaceRepository

_logger = logging.getLogger(__name__)

# Above the host's own git timeout (120 s) so the host's specific error
# surfaces instead of a generic server-side timeout.
_WORKTREE_TIMEOUT_S: float = 150.0

if TYPE_CHECKING:
    from omnigent.workspaces.worktree_lease import WorktreeLease, WorktreeLeaseManager

_attempt_worktree_lease_manager: WorktreeLeaseManager | None = None


class WorktreeProxyError(Exception):
    """
    Raised when the host reports a worktree operation failure.

    These are typically user-correctable input problems (branch
    already exists, not a git repo, bad base ref), so the route layer
    maps this to ``INVALID_INPUT`` (400).

    :param message: Human-readable error suitable for the API
        response body, e.g.
        ``"worktree creation failed: branch already exists"``.
    """

    def __init__(self, message: str) -> None:
        """
        Initialize with the user-facing error message.

        :param message: Error string surfaced to the API caller.
        """
        super().__init__(message)
        self.message = message


class WorktreeHostUnavailableError(WorktreeProxyError):
    """
    Raised when the host can't be reached for a worktree operation.

    Connection loss or no reply within the timeout — an infrastructure
    condition, not user input. The route layer maps this to
    ``CONFLICT`` (409). Subclasses :class:`WorktreeProxyError` so
    best-effort callers that catch the base type still catch it.
    """


@dataclass
class CreatedWorktree:
    """
    Result of a successful host worktree creation.

    :param worktree_path: Absolute path of the created worktree
        directory on the host, e.g.
        ``"/Users/alice/myrepo-worktrees/feature-login"``. Stored as
        the session ``workspace``.
    :param branch: The branch checked out in the worktree, e.g.
        ``"feature/login"``.
    """

    worktree_path: str
    branch: str
    lease: WorktreeLease | None = None


async def _await_host_worktree_result(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    pending: dict[str, asyncio.Future[dict[str, object]]],
    request_id: str,
    frame: str,
    op: str,
) -> dict[str, object]:
    """
    Send a worktree frame and await its matching result over the tunnel.

    Shared plumbing for the create/remove proxies: register a future on
    ``pending`` keyed by ``request_id``, enqueue ``frame``, await the
    reply, and clean up on every path.

    :param host_registry: Registry used to enqueue the outbound frame.
    :param host_conn: Live host connection.
    :param pending: The connection's pending-future map for this op
        (``pending_create_worktrees`` or ``pending_remove_worktrees``).
    :param request_id: Correlation id already embedded in ``frame``.
    :param frame: Encoded host frame to send.
    :param op: Short label for error messages, e.g.
        ``"worktree creation"``.
    :returns: The host's result dict (``status`` plus op-specific
        fields).
    :raises WorktreeHostUnavailableError: On connection loss or no
        reply within :data:`_WORKTREE_TIMEOUT_S`.
    """
    future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
    pending[request_id] = future
    try:
        try:
            host_registry.send_text(host_conn, frame)
        except ConnectionError as exc:
            raise WorktreeHostUnavailableError(
                f"host '{host_conn.host_id}' connection lost during {op}"
            ) from exc
        try:
            return await asyncio.wait_for(future, timeout=_WORKTREE_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise WorktreeHostUnavailableError(
                f"host '{host_conn.host_id}' did not respond to {op} within "
                f"{_WORKTREE_TIMEOUT_S:.0f}s (it may be running an older version "
                "that does not support worktrees)"
            ) from exc
    finally:
        pending.pop(request_id, None)


async def create_worktree_on_host(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    repo_path: str,
    branch_name: str,
    base_branch: str | None,
    target_path: str | None = None,
) -> CreatedWorktree:
    """
    Send a ``host.create_worktree`` frame and await the result.

    :param host_registry: Server-side registry; used to enqueue the
        outbound frame on the host's send queue.
    :param host_conn: Live host connection to create the worktree on.
    :param repo_path: Absolute path inside the source repo on the
        host — the canonical picked directory, e.g.
        ``"/Users/alice/myrepo"``.
    :param branch_name: New branch to create, e.g. ``"feature/login"``.
    :param base_branch: Optional base ref, e.g. ``"main"``. ``None``
        branches from the repo's current ``HEAD``.
    :returns: The created worktree's path and branch.
    :raises WorktreeHostUnavailableError: If the host connection drops
        or doesn't respond within :data:`_WORKTREE_TIMEOUT_S`.
    :raises WorktreeProxyError: If the host reports a worktree failure.
    """
    request_id = secrets.token_hex(8)
    frame = encode_host_frame(
        HostCreateWorktreeFrame(
            request_id=request_id,
            repo_path=repo_path,
            branch_name=branch_name,
            base_branch=base_branch,
            target_path=target_path,
        )
    )
    result = await _await_host_worktree_result(
        host_registry=host_registry,
        host_conn=host_conn,
        pending=host_conn.pending_create_worktrees,
        request_id=request_id,
        frame=frame,
        op="worktree creation",
    )
    if result.get("status") != "ok":
        raise WorktreeProxyError(
            f"worktree creation failed: {result.get('error') or 'host reported no detail'}"
        )
    worktree_path = result.get("worktree_path")
    branch = result.get("branch")
    if not isinstance(worktree_path, str) or not isinstance(branch, str):
        raise WorktreeProxyError("host returned an incomplete worktree result")
    return CreatedWorktree(worktree_path=worktree_path, branch=branch)


async def remove_worktree_on_host(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    worktree_path: str,
    branch: str | None,
    delete_branch: bool,
) -> None:
    """
    Send a ``host.remove_worktree`` frame and await the result.

    :param host_registry: Server-side registry; used to enqueue the
        outbound frame on the host's send queue.
    :param host_conn: Live host connection that owns the worktree.
    :param worktree_path: Absolute path of the worktree to remove on
        the host, e.g. ``"/Users/alice/myrepo-worktrees/feature-login"``.
    :param branch: Branch to delete when ``delete_branch`` is
        ``True``, e.g. ``"feature/login"``. ``None`` skips branch
        deletion.
    :param delete_branch: When ``True``, delete ``branch`` after
        removing the worktree directory.
    :raises WorktreeHostUnavailableError: If the host connection drops
        or doesn't respond within :data:`_WORKTREE_TIMEOUT_S`.
    :raises WorktreeProxyError: If the host reports a removal failure.
    """
    request_id = secrets.token_hex(8)
    frame = encode_host_frame(
        HostRemoveWorktreeFrame(
            request_id=request_id,
            worktree_path=worktree_path,
            branch=branch,
            delete_branch=delete_branch,
        )
    )
    result = await _await_host_worktree_result(
        host_registry=host_registry,
        host_conn=host_conn,
        pending=host_conn.pending_remove_worktrees,
        request_id=request_id,
        frame=frame,
        op="worktree removal",
    )
    if result.get("status") != "ok":
        raise WorktreeProxyError(
            f"worktree removal failed: {result.get('error') or 'host reported no detail'}"
        )


async def list_worktrees_on_host(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    repo_path: str,
) -> list[dict[str, object]]:
    """
    Send a ``host.list_worktrees`` frame and await the result.

    :param host_registry: Server-side registry; used to enqueue the
        outbound frame on the host's send queue.
    :param host_conn: Live host connection to list worktrees on.
    :param repo_path: Absolute path inside the source repo on the
        host — the canonical picked directory, e.g.
        ``"/Users/alice/myrepo"``.
    :returns: One dict per worktree with keys ``path``, ``branch``,
        ``is_main``, ``detached`` (main first).
    :raises WorktreeHostUnavailableError: If the host connection drops
        or doesn't respond within :data:`_WORKTREE_TIMEOUT_S`.
    :raises WorktreeProxyError: If the host reports a listing failure.
    """
    request_id = secrets.token_hex(8)
    frame = encode_host_frame(
        HostListWorktreesFrame(
            request_id=request_id,
            repo_path=repo_path,
        )
    )
    result = await _await_host_worktree_result(
        host_registry=host_registry,
        host_conn=host_conn,
        pending=host_conn.pending_list_worktrees,
        request_id=request_id,
        frame=frame,
        op="worktree listing",
    )
    if result.get("status") != "ok":
        raise WorktreeProxyError(
            f"worktree listing failed: {result.get('error') or 'host reported no detail'}"
        )
    worktrees = result.get("worktrees")
    if not isinstance(worktrees, list):
        raise WorktreeProxyError("host returned an incomplete worktree list")
    return worktrees


def get_attempt_worktree_lease_manager() -> WorktreeLeaseManager:
    """Return the process-wide attempt lease service used by production routes.

    The import is intentionally lazy: the lease service delegates Git I/O to
    this module's host proxies, so importing it at module load time would form
    a cycle.
    """
    global _attempt_worktree_lease_manager
    if _attempt_worktree_lease_manager is None:
        from omnigent.workspaces.worktree_lease import WorktreeLeaseManager

        _attempt_worktree_lease_manager = WorktreeLeaseManager()
    return _attempt_worktree_lease_manager


def configure_attempt_worktree_lease_store(store: object) -> None:
    """Attach the durable Run store to the process-wide lease manager."""
    global _attempt_worktree_lease_manager
    from omnigent.workspaces.worktree_lease import WorktreeLeaseManager

    _attempt_worktree_lease_manager = WorktreeLeaseManager(durable_store=store)


async def acquire_attempt_worktree_leases(
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
    """Production lifecycle seam for scheduler/session attempt startup."""
    return await get_attempt_worktree_lease_manager().acquire(
        host_id=host_id,
        host_registry=host_registry,
        host_conn=host_conn,
        workspace_root=workspace_root,
        repositories=repositories,
        attempt_id=attempt_id,
        owner_id=owner_id,
        run_id=run_id,
        child_session_id=child_session_id,
        branch_names=branch_names,
        target_paths=target_paths,
    )


def heartbeat_attempt_worktree_leases(leases: Iterable[WorktreeLease], *, owner_id: str) -> None:
    """Production lifecycle seam for attempt heartbeat updates."""
    get_attempt_worktree_lease_manager().heartbeat(leases, owner_id=owner_id)


async def release_attempt_worktree_leases(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    leases: Iterable[WorktreeLease],
    owner_id: str,
) -> None:
    """Production lifecycle seam for scheduler/session attempt teardown."""
    await get_attempt_worktree_lease_manager().release(
        host_registry=host_registry,
        host_conn=host_conn,
        leases=leases,
        owner_id=owner_id,
    )


async def release_attempt_worktree_leases_for_attempt(
    *,
    host_registry: HostRegistry | None,
    attempt_id: str,
) -> None:
    """Idempotently release the complete durable lease set for an Attempt."""
    await teardown_attempt_worktree_leases_for_attempt(
        host_registry=host_registry,
        attempt_id=attempt_id,
        runner_stop_confirmed=True,
    )


async def teardown_attempt_worktree_leases_for_attempt(
    *,
    host_registry: HostRegistry | None,
    attempt_id: str,
    runner_stop_confirmed: bool | None = None,
) -> None:
    """Release an Attempt workspace, or retain it when runner stop is unconfirmed."""
    manager = get_attempt_worktree_lease_manager()
    leases = manager.for_attempt(attempt_id)
    if not leases:
        return
    if runner_stop_confirmed is not True:
        await manager.defer_recovery(leases)
        return
    if host_registry is None:
        await manager.defer_recovery(leases)
        return
    host_conn = host_registry.get(leases[0].host_id)
    if host_conn is None:
        await manager.defer_recovery(leases)
        return
    try:
        await manager.release(
            host_registry=host_registry,
            host_conn=host_conn,
            leases=leases,
            owner_id=leases[0].owner,
        )
    except Exception:  # noqa: BLE001 - terminal cleanup must remain best-effort
        _logger.warning(
            "Attempt worktree cleanup deferred for attempt %s",
            attempt_id,
            exc_info=True,
        )


async def recover_expired_attempt_worktree_leases(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    safe_attempt_ids: set[str] | None = None,
) -> tuple[WorktreeLease, ...]:
    """Production lifecycle seam for stale-attempt recovery workers."""
    return await get_attempt_worktree_lease_manager().recover_expired(
        host_registry=host_registry,
        host_conn=host_conn,
        safe_attempt_ids=safe_attempt_ids,
    )


async def _confirm_recovery_attempts_stopped(
    *,
    manager: WorktreeLeaseManager,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    conversation_store: object,
) -> dict[str, str | None]:
    """Map recovery-safe Attempts to the exact runner binding that was checked."""
    from omnigent.server.routes._sessions.helpers import (
        _query_host_runner_status,
        _stop_session_host_runner,
    )

    safe: dict[str, str | None] = {}

    def _claim(
        *,
        child: object,
        child_id: str,
        attempt_id: str,
        runner_id: str | None,
    ) -> bool:
        workspace = getattr(child, "workspace", None)
        host_id = getattr(child, "host_id", None)
        if not isinstance(workspace, str) or not isinstance(host_id, str):
            return False
        return bool(
            conversation_store.claim_host_runner_recovery(
                child_id,
                attempt_id=attempt_id,
                expected_runner_id=runner_id,
                expected_workspace=workspace,
                host_id=host_id,
            )
        )

    for attempt_id in manager.recovery_candidate_attempt_ids(host_conn.host_id):
        leases = manager.for_attempt(attempt_id)
        if not leases:
            continue
        child_id = leases[0].child_session_id
        child = (
            conversation_store.get_conversation(child_id)
            if isinstance(child_id, str)
            else None
        )
        runner_id = getattr(child, "runner_id", None) if child is not None else None
        if child is None:
            safe[attempt_id] = None
            continue
        if not isinstance(runner_id, str) or not runner_id:
            if _claim(
                child=child,
                child_id=child_id,
                attempt_id=attempt_id,
                runner_id=None,
            ):
                safe[attempt_id] = None
            continue
        status = await _query_host_runner_status(host_conn, host_registry, runner_id)
        if status in {"dead", "unknown"}:
            current = conversation_store.get_conversation(child_id)
            if (
                current is not None
                and getattr(current, "runner_id", None) == runner_id
                and _claim(
                    child=current,
                    child_id=child_id,
                    attempt_id=attempt_id,
                    runner_id=runner_id,
                )
            ):
                safe[attempt_id] = runner_id
            continue
        if status != "alive":
            continue
        stopped = await _stop_session_host_runner(
            child.id,
            host_conn.host_id,
            runner_id,
            host_registry,
        )
        if stopped:
            current = conversation_store.get_conversation(child_id)
            if (
                current is not None
                and getattr(current, "runner_id", None) == runner_id
                and _claim(
                    child=current,
                    child_id=child_id,
                    attempt_id=attempt_id,
                    runner_id=runner_id,
                )
            ):
                safe[attempt_id] = runner_id
    return safe


async def _finalize_recovered_attempt_bindings(
    *,
    manager: WorktreeLeaseManager,
    recovered: tuple[WorktreeLease, ...],
    confirmed_runner_ids: dict[str, str | None],
    conversation_store: object,
) -> None:
    """Delete initial failed Children or clear retry bindings after lease removal."""
    for attempt_id in {lease.attempt_id for lease in recovered}:
        leases = tuple(lease for lease in recovered if lease.attempt_id == attempt_id)
        child_id = leases[0].child_session_id if leases else None
        if not isinstance(child_id, str):
            continue
        child = conversation_store.get_conversation(child_id)
        if child is None:
            continue
        expected_runner_id = confirmed_runner_ids.get(attempt_id)
        if getattr(child, "runner_id", None) != expected_runner_id:
            continue
        workspace = getattr(child, "workspace", None)
        host_id = getattr(child, "host_id", None)
        if not isinstance(workspace, str) or not isinstance(host_id, str):
            continue
        if manager.recovery_should_delete_child(attempt_id) and not manager.for_child(child_id):
            await conversation_store.delete_conversation_if_host_runner_recovery_claimed(
                child_id,
                attempt_id=attempt_id,
                expected_runner_id=expected_runner_id,
                expected_workspace=workspace,
                host_id=host_id,
            )
            continue
        conversation_store.finalize_host_runner_recovery(
            child_id,
            attempt_id=attempt_id,
            expected_runner_id=expected_runner_id,
            expected_workspace=workspace,
            host_id=host_id,
        )


async def _finalize_stranded_recovery_claims(
    *,
    manager: WorktreeLeaseManager,
    claims: list[dict[str, object]],
    conversation_store: object,
) -> None:
    """Finish claims whose worktree leases were released before a worker crash."""
    for claim in claims:
        child_id = claim.get("conversation_id")
        attempt_id = claim.get("attempt_id")
        workspace = claim.get("workspace")
        host_id = claim.get("host_id")
        runner_id = claim.get("runner_id")
        if not all(isinstance(value, str) for value in (child_id, attempt_id, workspace, host_id)):
            continue
        if manager.for_attempt(attempt_id):
            continue
        if manager.recovery_should_delete_child(attempt_id) and not manager.for_child(child_id):
            await conversation_store.delete_conversation_if_host_runner_recovery_claimed(
                child_id,
                attempt_id=attempt_id,
                expected_runner_id=runner_id if isinstance(runner_id, str) else None,
                expected_workspace=workspace,
                host_id=host_id,
            )
            continue
        conversation_store.finalize_host_runner_recovery(
            child_id,
            attempt_id=attempt_id,
            expected_runner_id=runner_id if isinstance(runner_id, str) else None,
            expected_workspace=workspace,
            host_id=host_id,
        )


async def maintain_attempt_worktree_leases(
    host_registry: HostRegistry,
    stop_event: asyncio.Event,
    *,
    conversation_store: object | None = None,
    liveness_lookup: object | None = None,
    interval_s: float = 30.0,
) -> None:
    """Heartbeat active leases and recover stale leases until shutdown."""
    from omnigent.workspaces.worktree_lease import WorktreeLeaseError

    while not stop_event.is_set():
        manager = get_attempt_worktree_lease_manager()
        workspace_ids = {lease.workspace_id for lease in manager.records}
        if conversation_store is not None:
            list_claim_workspaces = getattr(
                conversation_store,
                "list_host_runner_recovery_claim_workspace_ids",
                None,
            )
            if callable(list_claim_workspaces):
                workspace_ids.update(list_claim_workspaces())
        for workspace_id in sorted(workspace_ids or {0}):
            with workspace_scope(workspace_id):
                if conversation_store is not None and callable(liveness_lookup):
                    await manager.reconcile_hydrated_active(
                        host_registry=host_registry,
                        conversation_store=conversation_store,
                        liveness_lookup=liveness_lookup,
                    )
                recovery_claims = (
                    conversation_store.list_host_runner_recovery_claims()
                    if conversation_store is not None
                    else []
                )
                if conversation_store is not None:
                    try:
                        await _finalize_stranded_recovery_claims(
                            manager=manager,
                            claims=recovery_claims,
                            conversation_store=conversation_store,
                        )
                    except Exception:  # noqa: BLE001 - retry next maintenance cycle
                        _logger.warning(
                            "Stranded Host recovery finalization failed", exc_info=True
                        )
                host_ids = sorted(
                    {
                        lease.host_id
                        for lease in manager.records
                        if lease.workspace_id == current_workspace_id()
                    }
                    | {
                        str(claim["host_id"])
                        for claim in recovery_claims
                        if isinstance(claim.get("host_id"), str)
                    }
                )
                for host_id in host_ids:
                    host_conn = host_registry.get(host_id)
                    if host_conn is None:
                        continue
                    try:
                        if conversation_store is not None:
                            confirmed_runner_ids = await _confirm_recovery_attempts_stopped(
                                manager=manager,
                                host_registry=host_registry,
                                host_conn=host_conn,
                                conversation_store=conversation_store,
                            )
                            recovered = await recover_expired_attempt_worktree_leases(
                                host_registry=host_registry,
                                host_conn=host_conn,
                                safe_attempt_ids=set(confirmed_runner_ids),
                            )
                            await _finalize_recovered_attempt_bindings(
                                manager=manager,
                                recovered=recovered,
                                confirmed_runner_ids=confirmed_runner_ids,
                                conversation_store=conversation_store,
                            )
                        else:
                            await recover_expired_attempt_worktree_leases(
                                host_registry=host_registry,
                                host_conn=host_conn,
                            )
                    except (WorktreeLeaseError, WorktreeProxyError):
                        _logger.warning(
                            "Attempt worktree lease recovery failed for host %s",
                            host_id,
                            exc_info=True,
                        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except TimeoutError:
            continue
