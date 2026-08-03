"""Feishu installation and pairing entities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FeishuInstallationStatus(StrEnum):
    """The lifecycle state of a Feishu installation."""

    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass
class FeishuInstallation:
    """A Feishu app installation associated with a team."""

    id: str
    team_id: str
    app_id: str
    status: FeishuInstallationStatus = FeishuInstallationStatus.PENDING


@dataclass
class FeishuPairing:
    """A non-secret association between a Feishu installation and an agent.

    Secrets are deliberately not represented by this domain entity.
    """

    id: str
    agent_profile_id: str
    installation_id: str
