"""Local-host seam for parallel worktree and recovery acceptance tests."""

from __future__ import annotations

from dataclasses import dataclass


class WorkspaceSwitchRejected(RuntimeError):
    """Raised when a running Run attempts to change its immutable workspace."""

    failure_code = "RUNNING_WORKSPACE_SWITCH_REJECTED"


@dataclass
class FakeLease:
    run_id: str
    repository_id: str
    path: str
    state: str = "active"


class FakeHost:
    """Models independent sibling repositories and attempt-scoped leases."""

    def __init__(self, repositories: tuple[str, ...] = ("planet", "settlement")) -> None:
        self.repositories = tuple(repositories)
        self._snapshots = {repo: f"snapshot:{repo}" for repo in self.repositories}
        self.leases: list[FakeLease] = []
        self.fail_next_worker = False
        self.failures: list[str] = []

    @property
    def snapshots(self) -> dict[str, str]:
        return dict(self._snapshots)

    def create_parallel_leases(self, run_id: str) -> tuple[FakeLease, ...]:
        leases = tuple(
            FakeLease(run_id, repo, f"/tmp/omnigent/{run_id}/{repo}") for repo in self.repositories
        )
        self.leases.extend(leases)
        return leases

    def run_workers(self, run_id: str) -> str | None:
        if self.fail_next_worker:
            self.fail_next_worker = False
            code = "WORKER_PROCESS_EXIT_1"
            self.failures.append(code)
            return code
        return None

    def expire(self, run_id: str) -> None:
        for lease in self.leases:
            if lease.run_id == run_id:
                lease.state = "expired"

    def recover(self, run_id: str) -> tuple[FakeLease, ...]:
        recovered = tuple(lease for lease in self.leases if lease.run_id == run_id)
        for lease in recovered:
            lease.state = "released"
        return recovered

    def assert_siblings_unchanged(self, before: dict[str, str]) -> bool:
        return before == self._snapshots
