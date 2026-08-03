"""Contract tests for Lark routing and adapter safety checks."""

from __future__ import annotations

from omnigent.integrations.lark.adapter import LarkAdapter
from omnigent.integrations.lark.router import LarkRouter


class Coordinator:
    def __init__(self) -> None:
        self.received = []
        self.retry_count = 0

    def receive(self, request):
        self.received.append(request)
        return request

    def handle_action(self, action):
        self.retry_count += 1
        return {"action": action.action_id, "count": self.retry_count}


def _adapter() -> tuple[LarkAdapter, Coordinator]:
    coordinator = Coordinator()
    router = LarkRouter()
    router.bind("c", {"id": "team"}, coordinator, members={"u"})
    return LarkAdapter(router), coordinator


def test_worker_mention_is_routed_to_coordinator() -> None:
    adapter, coordinator = _adapter()
    result = adapter.receive(
        {
            "header": {"event_type": "im.message.receive_v1", "event_id": "m-1"},
            "event": {
                "message": {"chat_id": "c", "content": '{"text":"@backend 修复接口"}'},
                "sender": {"sender_id": "u"},
            },
        }
    )
    assert result.result.text == "@backend 修复接口"
    assert coordinator.received[-1].actor == "coordinator"


def test_card_action_is_idempotent_by_action_and_nonce() -> None:
    adapter, coordinator = _adapter()

    def event(event_id: str):
        return {
            "header": {"event_type": "card.action.trigger", "event_id": event_id},
            "event": {
                "chat_id": "c",
                "operator": {"open_id": "u"},
                "action": {"action_id": "retry", "nonce": "n-1", "value": {}},
            },
        }

    first = adapter.receive(event("a"))
    second = adapter.receive(event("b"))
    assert first.result == second.result
    assert coordinator.retry_count == 1


def test_unknown_thread_and_unauthorized_action_are_diagnostic() -> None:
    adapter, _ = _adapter()
    unknown = adapter.receive(
        {
            "header": {"event_type": "im.message.receive_v1", "event_id": "m-2"},
            "event": {
                "message": {"chat_id": "missing", "content": '{"text":"hello"}'},
                "sender": {"sender_id": "u"},
            },
        }
    )
    assert unknown.diagnostic and "unknown_thread" in unknown.diagnostic

