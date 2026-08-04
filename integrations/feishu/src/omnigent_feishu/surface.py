"""Idempotent Feishu menu provisioning with persistent-card fallback."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from omnigent_feishu.cards import NonceFactory, build_workspace_card, build_workspace_menu

SURFACE_PROFILE_ID = "omnigent-agent"
SURFACE_VERSION = 1
SurfaceStatus = Literal["pending", "ready", "partial", "failed"]


class FeishuSurfaceClient(Protocol):
    def supports_menu(self, installation_id: str) -> bool | Awaitable[bool]: ...
    def upsert_menu(
        self, installation_id: str, profile_id: str, menu: Mapping[str, object]
    ) -> object | Awaitable[object]: ...
    def upsert_persistent_card(
        self, installation_id: str, profile_id: str, card: Mapping[str, object]
    ) -> object | Awaitable[object]: ...


class SurfaceStore(Protocol):
    def get_surface(self, installation_id: str) -> Any: ...
    def save_surface(self, installation_id: str, values: Mapping[str, object]) -> Any: ...


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass(frozen=True)
class SurfaceResult:
    installation_id: str
    profile_id: str
    version: int
    status: SurfaceStatus
    surface_type: Literal["menu", "persistent_card", "none"]
    error: str | None
    provisioned_at: int

    def to_dict(self) -> dict[str, object]:
        return {
            "installation_id": self.installation_id,
            "surface_profile_id": self.profile_id,
            "surface_version": self.version,
            "status": self.status,
            "surface_type": self.surface_type,
            "error": self.error,
            "last_provisioned_at": self.provisioned_at,
        }


class BotSurfaceProvisioner:
    def __init__(
        self,
        client: FeishuSurfaceClient,
        *,
        store: SurfaceStore,
        signing_secret: str,
        clock: Callable[[], int] | None = None,
        nonce_factory: NonceFactory | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._secret = signing_secret
        self._clock = clock or (lambda: int(time.time()))
        self._nonce = nonce_factory

    async def status(self, installation_id: str) -> Mapping[str, object] | None:
        return await _await(self._store.get_surface(installation_id))

    async def ensure(
        self,
        installation_id: str,
        *,
        agent_id: str | None = None,
        workspace_id: str | None = None,
    ) -> SurfaceResult:
        error: str | None = None
        try:
            supported = bool(await _await(self._client.supports_menu(installation_id)))
        except Exception:  # noqa: BLE001 - provider boundary is deliberately sanitized
            supported = False
            error = "menu capability probe failed"
        if supported:
            try:
                await _await(
                    self._client.upsert_menu(
                        installation_id, SURFACE_PROFILE_ID, build_workspace_menu()
                    )
                )
                return await self._save(installation_id, "ready", "menu", None)
            except Exception:  # noqa: BLE001 - provider boundary is deliberately sanitized
                error = "menu provisioning failed"
        try:
            await _await(
                self._client.upsert_persistent_card(
                    installation_id,
                    SURFACE_PROFILE_ID,
                    build_workspace_card(
                        signing_secret=self._secret,
                        agent_id=agent_id,
                        workspace_id=workspace_id,
                        nonce_factory=self._nonce,
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - provider boundary is deliberately sanitized
            return await self._save(
                installation_id, "failed", "none", "surface provisioning failed"
            )
        return await self._save(
            installation_id,
            "partial",
            "persistent_card",
            f"{error or 'menu unavailable'}; using persistent card",
        )

    async def _save(
        self,
        installation_id: str,
        status: SurfaceStatus,
        surface_type: Literal["menu", "persistent_card", "none"],
        error: str | None,
    ) -> SurfaceResult:
        result = SurfaceResult(
            installation_id,
            SURFACE_PROFILE_ID,
            SURFACE_VERSION,
            status,
            surface_type,
            error,
            self._clock(),
        )
        await _await(self._store.save_surface(installation_id, result.to_dict()))
        return result


LarkSurfaceClient = FeishuSurfaceClient

__all__ = [
    "SURFACE_PROFILE_ID",
    "SURFACE_VERSION",
    "BotSurfaceProvisioner",
    "FeishuSurfaceClient",
    "SurfaceResult",
]
