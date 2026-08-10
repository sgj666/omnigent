"""Project entity — persisted in the ``projects`` table.

A :class:`Project` is a user-defined, owner-private container that groups
related sessions. It exists independently of its member sessions (it can be
empty), which is why it is a first-class row rather than the implicit
``omni_project`` label it supersedes. Session membership lives on the
conversation's metadata row (``project_id``), not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Project:
    """
    A project persisted in the ``projects`` table.

    :param id: UUID primary key (bare 32-char hex string, no dashes).
    :param name: Human-readable project name, unique per owner.
    :param owner_user_id: User the project belongs to, e.g.
        ``"alice@example.com"``. ``None`` in single-user mode. Ownership is
        stamped on the row (not derived from a permission table) because
        projects are owner-private and carry no ACL of their own.
    :param created_at: Unix epoch seconds at row creation.
    :param updated_at: Unix epoch seconds of the last write, or ``None`` if the
        row has never been updated.
    :param config: Project execution binding and optional session defaults.
        When both ``host_id`` and ``workspace`` are present, the server treats
        them as the authoritative location for sessions filed in this project;
        a managed-sandbox binding may omit ``workspace`` for an empty sandbox.
        Other keys remain client-owned defaults. Older projects may have an
        empty config.
    """

    id: str
    name: str
    owner_user_id: str | None
    created_at: int
    updated_at: int | None = None
    config: dict[str, Any] = field(default_factory=dict)
