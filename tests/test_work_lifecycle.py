from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from omnigent.work_lifecycle import (
    InboxCategory,
    InboxItemProjection,
    TaskLifecycleEvent,
    TaskLifecycleEventType,
    TaskRunState,
)


def _event_payload() -> dict[str, object]:
    return {
        "event_id": "evt_1",
        "idempotency_key": "run_1:succeeded:1",
        "type": "run.succeeded",
        "occurred_at": "2026-08-06T12:30:00Z",
        "task_id": "task_1",
        "run_id": "run_1",
        "session_id": "conv_1",
        "source": {"kind": "runtime", "id": "runner_1"},
        "summary": "Research completed",
        "task_state": "done",
        "run_state": "succeeded",
        "result": {"summary": "Three findings", "artifact_ids": ["artifact_1"]},
    }


def test_parses_normalized_lifecycle_event() -> None:
    event = TaskLifecycleEvent.model_validate(_event_payload())

    assert event.type is TaskLifecycleEventType.RUN_SUCCEEDED
    assert event.run_state is TaskRunState.SUCCEEDED
    assert event.occurred_at.tzinfo is not None
    assert event.result is not None
    assert event.result.artifact_ids == ["artifact_1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_state", "complete"),
        ("type", "run.finished"),
        ("occurred_at", "2026-08-06T12:30:00"),
    ],
)
def test_rejects_unknown_values_and_naive_timestamps(field: str, value: str) -> None:
    payload = _event_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        TaskLifecycleEvent.model_validate(payload)


def test_run_events_require_run_id() -> None:
    payload = _event_payload()
    payload.pop("run_id")

    with pytest.raises(ValidationError, match="require run_id"):
        TaskLifecycleEvent.model_validate(payload)


def test_failed_events_require_failure_details() -> None:
    payload = _event_payload()
    payload.update({"type": "run.failed", "run_state": "failed"})
    payload.pop("result")

    with pytest.raises(ValidationError, match="require failure details"):
        TaskLifecycleEvent.model_validate(payload)


def test_inbox_projection_requires_explicit_unread_policy_and_dedupe_key() -> None:
    item = InboxItemProjection(
        item_id="inbox_1",
        dedupe_key="task_1:run_1:completed",
        source_event_id="evt_1",
        category=InboxCategory.COMPLETED,
        task_id="task_1",
        run_id="run_1",
        title="Task completed",
        summary="Research completed",
        is_unread=True,
        created_at=datetime.now(timezone.utc),
    )

    assert item.is_unread is True
    assert item.dedupe_key == "task_1:run_1:completed"

    with pytest.raises(ValidationError):
        InboxItemProjection.model_validate(
            {
                "item_id": "inbox_2",
                "source_event_id": "evt_2",
                "category": "progress",
                "task_id": "task_1",
                "title": "Progress",
                "summary": "Halfway",
                "created_at": "2026-08-06T12:30:00Z",
            }
        )
