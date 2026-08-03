"""Pure state values reduced from team harness ledger events."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnigent.entities.run import RunStatus


@dataclass(frozen=True)
class RunState:
    """The replayable run state required by the harness reducer."""

    run_id: str
    status: RunStatus
    applied_event_ids: frozenset[str] = field(default_factory=frozenset)
    coordinator_wake_correlation_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def queued(cls, run_id: str) -> RunState:
        """Create the initial state for a newly requested run."""

        return cls(run_id=run_id, status=RunStatus.QUEUED)

    @classmethod
    def running(cls, run_id: str) -> RunState:
        """Create a running state for a run already dispatched."""

        return cls(run_id=run_id, status=RunStatus.RUNNING)

    @classmethod
    def completed(cls, run_id: str) -> RunState:
        """Create a terminal successful state for a run."""

        return cls(run_id=run_id, status=RunStatus.COMPLETED)

    @classmethod
    def failed(cls, run_id: str) -> RunState:
        """Create a terminal failed state for a run."""

        return cls(run_id=run_id, status=RunStatus.FAILED)

    @classmethod
    def cancelled(cls, run_id: str) -> RunState:
        """Create a terminal cancelled state for a run."""

        return cls(run_id=run_id, status=RunStatus.CANCELLED)
