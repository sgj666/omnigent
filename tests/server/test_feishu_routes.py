"""Route contracts for Feishu PersonalAgent installation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.integrations.lark.credentials import (
    FeishuCredentialCipher,
    FeishuInstallationCredential,
)
from omnigent.integrations.lark.device_flow import (
    FeishuDeviceFlowError,
    FeishuDeviceSession,
    FeishuRegistration,
)
from omnigent.server.routes.feishu import create_feishu_router


class FakeFlow:
    def __init__(
        self,
        result: FeishuRegistration | None = None,
        error: FeishuDeviceFlowError | None = None,
    ) -> None:
        self.result = result
        self.error = error

    async def begin(self) -> FeishuDeviceSession:
        if self.error:
            raise self.error
        return FeishuDeviceSession("session-1", "https://qr.example/session-1", 3, 180)

    async def poll(self, session: str) -> FeishuRegistration | None:
        assert session == "session-1"
        if self.error:
            raise self.error
        return self.result


def _client(
    flow: FakeFlow,
    saved: list[tuple[FeishuInstallationCredential, Mapping[str, Any]]],
) -> TestClient:
    app = FastAPI()

    def save(
        credential: FeishuInstallationCredential, *, bot: Mapping[str, Any]
    ) -> dict[str, str]:
        saved.append((credential, bot))
        return {"tenant_key": "tenant-1"}

    app.include_router(create_feishu_router(flow, FeishuCredentialCipher(b"test-key"), save))  # type: ignore[arg-type]
    return TestClient(app)


def test_begin_returns_qr_url_session_and_poll_timing() -> None:
    client = _client(FakeFlow(), [])

    response = client.post("/feishu/installations")

    assert response.status_code == 200
    assert response.json() == {
        "object": "feishu.installation_session",
        "session": "session-1",
        "verification_uri_complete": "https://qr.example/session-1",
        "interval": 3,
        "expires_in": 180,
        "status": "pending",
    }


def test_completed_poll_persists_only_ciphertext_and_never_returns_secret() -> None:
    secret = "never-expose-me"
    saved: list[tuple[FeishuInstallationCredential, Mapping[str, Any]]] = []
    registration = FeishuRegistration(
        app_id="cli_123",
        app_secret=secret,
        installer_open_id="ou_installer",
        bot={"open_id": "ou_bot"},
    )
    client = _client(FakeFlow(registration), saved)

    response = client.get("/feishu/installations/session-1")

    assert response.status_code == 200
    assert secret not in response.text
    assert response.json()["installer_open_id"] == "ou_installer"
    credential, bot = saved[0]
    assert credential.app_secret_ciphertext != secret
    assert FeishuCredentialCipher(b"test-key").decrypt(credential.app_secret_ciphertext) == secret
    assert bot == {"open_id": "ou_bot"}


def test_denied_and_network_errors_have_actionable_statuses() -> None:
    denied = _client(
        FakeFlow(error=FeishuDeviceFlowError("denied", "Feishu registration was denied")), []
    )
    network = _client(
        FakeFlow(error=FeishuDeviceFlowError("network", "Could not reach Feishu", retryable=True)),
        [],
    )

    denied_response = denied.get("/feishu/installations/session-1")
    network_response = network.post("/feishu/installations")

    assert denied_response.status_code == 403
    assert network_response.status_code == 503
    assert network_response.headers["retry-after"] == "5"
