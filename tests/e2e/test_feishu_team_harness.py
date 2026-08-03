"""Small, network-free acceptance of the Feishu team-harness seams.

These tests deliberately stop at the Coordinator/Adapter boundary.  The
provider and host fakes exercise the same idempotency, lease and diagnostic
contracts as a deployed server while keeping CI independent of Feishu and Git
credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from omnigent.entities.run import Run, RunStatus
from omnigent.integrations.lark.adapter import LarkAdapter
from omnigent.integrations.lark.router import LarkRouter, RunRequest
from tests.fixtures.fake_host import FakeHost, WorkspaceSwitchRejected
from tests.fixtures.fake_lark import FakeLark


@dataclass
class AcceptedRun:
    run: Run
    attempts: int = 0
    failure_code: str | None = None


class HarnessCoordinator:
    """Explicit Coordinator seam used by the e2e tests.

    It persists run state in the injected dictionary, so constructing a new
    instance simulates a process restart/reconciliation pass.
    """

    def __init__(
        self, host: FakeHost, lark: FakeLark, ledger: dict[str, AcceptedRun] | None = None
    ) -> None:
        self.id = "coordinator-1"
        self.host, self.lark = host, lark
        self.ledger = ledger if ledger is not None else {}
        self.action_count = 0

    def submit(self, request: RunRequest) -> str:
        workspace_id = request.workspace_id or "luxury-resale-settlement"
        run = Run.new(request.team_id, workspace_id, source="feishu")
        accepted = AcceptedRun(run)
        leases = self.host.create_parallel_leases(run.id)
        accepted.attempts = len(leases)
        accepted.failure_code = self.host.run_workers(run.id)
        self.ledger[run.id] = accepted
        if accepted.failure_code:
            self.lark.notify(
                "failure",
                run.id,
                failure_code=accepted.failure_code,
                next_action="inspect worker logs and retry",
            )
        else:
            self.lark.notify("final", run.id, status="completed")
        return run.id

    def handle_action(self, _action: object) -> str:
        self.action_count += 1
        return "accepted"

    def restart(self) -> HarnessCoordinator:
        return HarnessCoordinator(self.host, self.lark, self.ledger)

    def switch_workspace(self, run_id: str, workspace_id: str) -> None:
        accepted = self.ledger[run_id]
        if accepted.run.status is not RunStatus.COMPLETED:
            raise WorkspaceSwitchRejected(
                f"run {run_id} is running in {accepted.run.workspace_id}; select {workspace_id} "
                "for a subsequent run"
            )


@pytest.fixture
def fake_lark() -> FakeLark:
    return FakeLark()


@pytest.fixture
def fake_host() -> FakeHost:
    return FakeHost(("planet", "settlement"))


def _adapter(fake_lark: FakeLark, coordinator: HarnessCoordinator) -> LarkAdapter:
    router = LarkRouter(coordinator_callback=coordinator.submit)
    router.bind(
        "chat-1",
        {"id": "team-1"},
        coordinator,
        workspace_id="luxury-resale-settlement",
        members={"user-1"},
    )
    return LarkAdapter(router)


def test_feishu_run_executes_parallel_multi_repo_attempts_and_notifies(
    fake_lark: FakeLark,
    fake_host: FakeHost,
) -> None:
    before = fake_host.snapshots
    coordinator = HarnessCoordinator(fake_host, fake_lark)
    adapter = _adapter(fake_lark, coordinator)
    result = fake_lark.emit_text(
        adapter,
        event_id="message-1",
        chat_id="chat-1",
        sender_id="user-1",
        text="修复清分后不支持判商家责任",
    )
    run_id = result.result

    accepted = coordinator.ledger[run_id]
    assert accepted.attempts >= 2
    assert accepted.run.workspace_id == "luxury-resale-settlement"
    assert fake_host.assert_siblings_unchanged(before)
    assert fake_lark.has_notification("final", run_id)


def test_duplicate_card_is_idempotent_and_worker_mentions_still_use_coordinator(
    fake_lark: FakeLark,
    fake_host: FakeHost,
) -> None:
    coordinator = HarnessCoordinator(fake_host, fake_lark)
    adapter = _adapter(fake_lark, coordinator)
    first = fake_lark.emit_card(
        adapter,
        event_id="card-1",
        action_id="retry",
        nonce="n-1",
        chat_id="chat-1",
        actor_id="user-1",
    )
    second = fake_lark.emit_card(
        adapter,
        event_id="card-1",
        action_id="retry",
        nonce="n-1",
        chat_id="chat-1",
        actor_id="user-1",
    )
    assert first.result == second.result == "accepted"
    assert second.duplicate is True
    assert coordinator.action_count == 1

    message = fake_lark.emit_text(
        adapter,
        event_id="message-worker",
        chat_id="chat-1",
        sender_id="user-1",
        text="@worker 请修复",
    )
    assert coordinator.ledger[message.result].run.source == "feishu"


def test_worker_failure_surfaces_failure_code_and_recovery_after_coordinator_restart(
    fake_lark: FakeLark,
    fake_host: FakeHost,
) -> None:
    fake_host.fail_next_worker = True
    ledger: dict[str, AcceptedRun] = {}
    coordinator = HarnessCoordinator(fake_host, fake_lark, ledger)
    adapter = _adapter(fake_lark, coordinator)
    result = fake_lark.emit_text(
        adapter,
        event_id="message-failed",
        chat_id="chat-1",
        sender_id="user-1",
        text="run failing worker",
    )
    run_id = result.result
    assert ledger[run_id].failure_code == "WORKER_PROCESS_EXIT_1"
    assert fake_lark.has_notification("failure", run_id)
    restarted = coordinator.restart()
    assert restarted.ledger[run_id].failure_code == "WORKER_PROCESS_EXIT_1"


def test_device_flow_timeout_websocket_reconnect_lease_recovery_and_menu_fallback(
    fake_lark: FakeLark,
    fake_host: FakeHost,
) -> None:
    fake_lark.poll_result = {"status": "expired"}
    assert fake_lark.poll_install()["failure_code"] == "DEVICE_FLOW_EXPIRED"

    fake_lark.connect()
    fake_lark.disconnect()
    fake_lark.reconnect()
    assert fake_lark.connected and fake_lark.reconnect_count == 1

    leases = fake_host.create_parallel_leases("run-recovery")
    fake_host.expire("run-recovery")
    assert all(lease.state == "expired" for lease in leases)
    assert len(fake_host.recover("run-recovery")) == 2
    assert all(lease.state == "released" for lease in leases)

    fake_lark.menu_supported = False
    surface = fake_lark.ensure_surface("installation-1")
    assert surface == {"status": "partial", "surface_type": "persistent_card"}
    assert fake_lark.ensure_surface("installation-1") == surface
    assert fake_lark.created_surface_count == 1


def test_running_workspace_switch_is_rejected(fake_lark: FakeLark, fake_host: FakeHost) -> None:
    coordinator = HarnessCoordinator(fake_host, fake_lark)
    # Keep a run in the running state for this boundary check.
    run = Run.new("team-1", "workspace-a", source="feishu")
    coordinator.ledger[run.id] = AcceptedRun(run)
    with pytest.raises(WorkspaceSwitchRejected) as error:
        coordinator.switch_workspace(run.id, "workspace-b")
    assert error.value.failure_code == "RUNNING_WORKSPACE_SWITCH_REJECTED"
