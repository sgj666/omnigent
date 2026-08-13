"""Tests for the durable development-delivery workflow vocabulary."""

from omnigent.entities.delivery_workflow import DeliveryPhase, DeliveryStatus


def test_delivery_phases_match_the_zhuanharness_contract() -> None:
    assert [phase.value for phase in DeliveryPhase] == [
        "intake",
        "preflight",
        "requirement",
        "research",
        "proposal",
        "planning",
        "implementation",
        "integration",
        "testing",
        "verification",
        "review",
        "knowledge_close",
        "archive",
        "pending_delivery",
        "delivered",
    ]


def test_blocked_is_a_status_not_a_phase() -> None:
    assert DeliveryStatus.BLOCKED.value == "blocked"
    assert "blocked" not in {phase.value for phase in DeliveryPhase}
