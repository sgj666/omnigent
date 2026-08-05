"""Idempotent provisioning for the default Feishu bot workspace surface."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from .cards import NonceFactory, build_workspace_card, build_workspace_menu

SURFACE_PROFILE_ID = "omnigent-team"
SURFACE_VERSION = 1

SurfaceStatus = Literal["pending", "ready", "partial", "failed"]
SurfaceType = Literal["menu", "persistent_card", "none"]


class LarkSurfaceClient(Protocol):
    """Provider operations required by the provisioner."""

    def supports_menu(self, installation_id: str) -> bool: ...

    def upsert_menu(
        self,
        installation_id: str,
        profile_id: str,
        menu: Mapping[str, object],
    ) -> object: ...

    def upsert_persistent_card(
        self,
        installation_id: str,
        profile_id: str,
        card: Mapping[str, object],
    ) -> object: ...


class SurfaceStore(Protocol):
    """Durable installation surface state boundary."""

    def load(self, installation_id: str) -> Mapping[str, object] | None: ...

    def save(self, installation_id: str, values: Mapping[str, object]) -> None: ...


class SurfaceLedger(Protocol):
    """Append-only audit boundary for provisioning lifecycle events."""

    def append(self, event: Mapping[str, object]) -> object: ...


@dataclass(frozen=True)
class SurfaceResult:
    """A provisioned surface and its canonical installation state."""

    installation_id: str
    surface_profile_id: str
    surface_version: int
    status: SurfaceStatus
    error: str | None
    last_provisioned_at: int
    surface_type: SurfaceType

    def persistence_values(self) -> dict[str, object]:
        """Return exactly the surface fields persisted on an installation."""
        return {
            "surface_profile_id": self.surface_profile_id,
            "surface_version": self.surface_version,
            "provision_status": self.status,
            "provision_error": self.error,
            "last_provisioned_at": self.last_provisioned_at,
        }

    def to_dict(self) -> dict[str, object]:
        """Return the non-secret API representation."""
        return {
            "object": "feishu.bot_surface",
            "installation_id": self.installation_id,
            "surface_profile_id": self.surface_profile_id,
            "surface_version": self.surface_version,
            "status": self.status,
            "error": self.error,
            "last_provisioned_at": self.last_provisioned_at,
            "surface_type": self.surface_type,
        }

    @classmethod
    def from_record(
        cls, installation_id: str, record: Mapping[str, object]
    ) -> SurfaceResult | None:
        """Decode a stored surface record, returning none for incomplete state."""
        profile_id = record.get("surface_profile_id")
        version = record.get("surface_version")
        status = record.get("provision_status")
        provisioned_at = record.get("last_provisioned_at")
        error = record.get("provision_error")
        if (
            not isinstance(profile_id, str)
            or not isinstance(version, int)
            or status not in {"pending", "ready", "partial", "failed"}
            or not isinstance(provisioned_at, int)
            or (error is not None and not isinstance(error, str))
        ):
            return None
        surface_type: SurfaceType = (
            "menu" if status == "ready" else "persistent_card" if status == "partial" else "none"
        )
        return cls(
            installation_id=installation_id,
            surface_profile_id=profile_id,
            surface_version=version,
            status=cast(SurfaceStatus, status),
            error=error,
            last_provisioned_at=provisioned_at,
            surface_type=surface_type,
        )


class BotSurfaceProvisioner:
    """Create or update one stable workspace surface per installation."""

    def __init__(
        self,
        client: LarkSurfaceClient,
        *,
        store: SurfaceStore,
        signing_secret: str,
        ledger: SurfaceLedger | None = None,
        clock: Callable[[], int] | None = None,
        nonce_factory: NonceFactory | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._ledger = ledger
        self._signing_secret = signing_secret
        self._clock = clock or (lambda: int(time.time()))
        self._nonce_factory = nonce_factory

    def status(self, installation_id: str) -> SurfaceResult | None:
        """Load the last persisted surface state without contacting Feishu."""
        record = self._store.load(installation_id)
        if record is None:
            return None
        return SurfaceResult.from_record(installation_id, record)

    def ensure(self, installation_id: str) -> SurfaceResult:
        """Upsert the preferred menu or its persistent-card fallback."""
        current = self._store.load(installation_id)
        operation = "surface_updated" if current is not None else "surface_initialized"
        error: str | None = None
        try:
            menu_supported = self._client.supports_menu(installation_id)
        except Exception as exc:  # noqa: BLE001 - provider capability seam
            menu_supported = False
            error = f"application menu probe failed: {exc}"

        if menu_supported:
            try:
                self._client.upsert_menu(
                    installation_id,
                    SURFACE_PROFILE_ID,
                    build_workspace_menu(),
                )
                return self._complete(
                    installation_id,
                    status="ready",
                    surface_type="menu",
                    error=None,
                    events=(operation,),
                )
            except Exception as exc:  # noqa: BLE001 - provider API boundary
                error = f"application menu update failed: {exc}"

        fallback_error = error or "application menu unavailable"
        try:
            self._client.upsert_persistent_card(
                installation_id,
                SURFACE_PROFILE_ID,
                build_workspace_card(
                    signing_secret=self._signing_secret,
                    nonce_factory=self._nonce_factory,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - provider API boundary
            return self._complete(
                installation_id,
                status="failed",
                surface_type="none",
                error=f"{fallback_error}; persistent card update failed: {exc}",
                events=("surface_failed",),
            )
        return self._complete(
            installation_id,
            status="partial",
            surface_type="persistent_card",
            error=f"{fallback_error}; using persistent card",
            events=(operation, "surface_degraded"),
        )

    def _complete(
        self,
        installation_id: str,
        *,
        status: SurfaceStatus,
        surface_type: SurfaceType,
        error: str | None,
        events: tuple[str, ...],
    ) -> SurfaceResult:
        result = SurfaceResult(
            installation_id=installation_id,
            surface_profile_id=SURFACE_PROFILE_ID,
            surface_version=SURFACE_VERSION,
            status=status,
            error=error,
            last_provisioned_at=self._clock(),
            surface_type=surface_type,
        )
        self._store.save(installation_id, result.persistence_values())
        if self._ledger is not None:
            for event in events:
                self._ledger.append(
                    {
                        "event": event,
                        "installation_id": installation_id,
                        **result.persistence_values(),
                        "surface_type": surface_type,
                    }
                )
        return result


__all__ = [
    "SURFACE_PROFILE_ID",
    "SURFACE_VERSION",
    "BotSurfaceProvisioner",
    "LarkSurfaceClient",
    "SurfaceLedger",
    "SurfaceResult",
    "SurfaceStore",
]
