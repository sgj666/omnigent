"""Pure projection of real Session lifecycle events into Run records."""

from __future__ import annotations

from typing import Protocol

from omnigent.entities.run_projection import ProjectionEvent, ProjectionResult


class _ProjectionStore(Protocol):
    def apply_projection_event(self, event: ProjectionEvent) -> ProjectionResult: ...


class RunProjector:
    """Persist a Session event projection without performing execution work."""

    def __init__(self, store: _ProjectionStore) -> None:
        self._store = store

    def apply(self, event: ProjectionEvent) -> ProjectionResult:
        return self._store.apply_projection_event(event)
