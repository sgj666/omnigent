"""Contract tests for the idempotent Feishu bot workspace surface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from omnigent.integrations.lark.cards import WORKSPACE_ACTIONS
from omnigent.integrations.lark.surface import (
    BotSurfaceProvisioner,
    SurfaceResult,
)


class FakeLark:
    def __init__(self, *, menu_supported: bool, card_error: str | None = None) -> None:
        self.menu_supported = menu_supported
        self.card_error = card_error
        self.resources: set[tuple[str, str]] = set()
        self.created_surface_count = 0
        self.menu: Mapping[str, object] | None = None
        self.card: Mapping[str, object] | None = None

    def supports_menu(self, installation_id: str) -> bool:
        assert installation_id == "installation-1"
        return self.menu_supported

    def _upsert(self, installation_id: str, profile_id: str) -> str:
        key = (installation_id, profile_id)
        if key not in self.resources:
            self.resources.add(key)
            self.created_surface_count += 1
        return f"surface:{installation_id}:{profile_id}"

    def upsert_menu(
        self, installation_id: str, profile_id: str, menu: Mapping[str, object]
    ) -> str:
        self.menu = menu
        return self._upsert(installation_id, profile_id)

    def upsert_persistent_card(
        self, installation_id: str, profile_id: str, card: Mapping[str, object]
    ) -> str:
        if self.card_error is not None:
            raise RuntimeError(self.card_error)
        self.card = card
        return self._upsert(installation_id, profile_id)


class MemorySurfaceStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}

    def load(self, installation_id: str) -> Mapping[str, object] | None:
        return self.records.get(installation_id)

    def save(self, installation_id: str, values: Mapping[str, object]) -> None:
        self.records[installation_id] = dict(values)


class MemoryLedger:
    def __init__(self) -> None:
        self.events: list[Mapping[str, object]] = []

    def append(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))


def _provisioner(
    lark: FakeLark, store: MemorySurfaceStore, ledger: MemoryLedger
) -> BotSurfaceProvisioner:
    return BotSurfaceProvisioner(
        lark,
        store=store,
        ledger=ledger,
        signing_secret="server-only-secret",
        clock=lambda: 1_722_830_400,
        nonce_factory=lambda action: f"nonce-{action}",
    )


def test_surface_falls_back_to_persistent_card_when_menu_is_unavailable() -> None:
    lark = FakeLark(menu_supported=False)
    store = MemorySurfaceStore()
    ledger = MemoryLedger()

    result = _provisioner(lark, store, ledger).ensure("installation-1")

    assert result.status == "partial"
    assert result.surface_type == "persistent_card"
    assert store.records["installation-1"] == {
        "surface_profile_id": "omnigent-team",
        "surface_version": 1,
        "provision_status": "partial",
        "provision_error": "application menu unavailable; using persistent card",
        "last_provisioned_at": 1_722_830_400,
    }
    assert [event["event"] for event in ledger.events] == [
        "surface_initialized",
        "surface_degraded",
    ]


def test_surface_provision_is_idempotent_across_restart_and_manual_reinit() -> None:
    lark = FakeLark(menu_supported=True)
    store = MemorySurfaceStore()
    ledger = MemoryLedger()

    _provisioner(lark, store, ledger).ensure("installation-1")
    restarted = _provisioner(lark, store, ledger)
    result = restarted.ensure("installation-1")

    assert result.status == "ready"
    assert result.surface_type == "menu"
    assert lark.created_surface_count == 1
    assert [event["event"] for event in ledger.events] == [
        "surface_initialized",
        "surface_updated",
    ]
    assert lark.menu is not None
    entries = cast(list[dict[str, str]], lark.menu["top_entries"])
    assert [entry["action"] for entry in entries] == [
        "team_work",
        "all_sessions",
        "code_changes",
        "settings",
    ]


def test_surface_failure_is_persisted_and_audited() -> None:
    lark = FakeLark(menu_supported=False, card_error="card permission denied")
    store = MemorySurfaceStore()
    ledger = MemoryLedger()

    result = _provisioner(lark, store, ledger).ensure("installation-1")

    assert result.status == "failed"
    assert result.error == (
        "application menu unavailable; persistent card update failed: card permission denied"
    )
    assert store.records["installation-1"]["provision_status"] == "failed"
    assert [event["event"] for event in ledger.events] == ["surface_failed"]


def test_persistent_card_has_fixed_actions_and_only_signed_server_fields() -> None:
    lark = FakeLark(menu_supported=False)
    provisioner = _provisioner(lark, MemorySurfaceStore(), MemoryLedger())

    provisioner.ensure("installation-1")

    assert lark.card is not None
    elements = cast(list[dict[str, object]], lark.card["elements"])
    actions = [
        button
        for element in elements
        for button in cast(list[dict[str, object]], element.get("actions", ()))
    ]
    button_values = [cast(dict[str, object], button["value"]) for button in actions]
    button_texts = [cast(dict[str, str], button["text"]) for button in actions]
    labels_and_actions = [
        (text["content"], value["action_id"])
        for text, value in zip(button_texts, button_values, strict=True)
    ]
    assert labels_and_actions == [(label, action) for action, label in WORKSPACE_ACTIONS]
    allowed = {"action_id", "run_id", "task_id", "attempt_id", "nonce", "signature"}
    assert all(set(value) == allowed for value in button_values)
    assert all(value["signature"] for value in button_values)


def test_surface_result_serializes_canonical_persistence_fields() -> None:
    result = SurfaceResult(
        installation_id="installation-1",
        surface_profile_id="omnigent-team",
        surface_version=1,
        status="ready",
        error=None,
        last_provisioned_at=123,
        surface_type="menu",
    )

    assert result.persistence_values() == {
        "surface_profile_id": "omnigent-team",
        "surface_version": 1,
        "provision_status": "ready",
        "provision_error": None,
        "last_provisioned_at": 123,
    }
    assert result.to_dict()["installation_id"] == "installation-1"
