"""Tests for the ``GET /v1/usage`` report builder and its helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from omnigent.entities import FunctionCallData, NewConversationItem, Project, WorkItem, WorkItemRun
from omnigent.server.auth import RESERVED_USER_LOCAL
from omnigent.server.routes.usage import (
    _build_usage_report,
    _day_offset,
    _session_cost,
    _session_models,
    _session_priced,
    _task_run_range_start,
    _usage_count,
)
from omnigent.stores.conversation_store.sqlalchemy_store import (
    SqlAlchemyConversationStore,
)
from omnigent.work_lifecycle import TaskRunState, TaskRunTrigger, TaskState

_DAY = 86_400
# Agent ids are stored as 16-byte uuids, so tests use a valid 32-char hex id.
_AGENT_ID = "0123456789abcdef0123456789abcdef"
_BUNDLE_DIGEST = "a" * 64


def test_day_offset() -> None:
    # Inclusive windows: today + the 6 prior days = a 7-day window.
    assert _day_offset("2026-07-22", days=6) == "2026-07-16"
    assert _day_offset("2026-07-22", days=29) == "2026-06-23"
    # Crosses a month boundary correctly.
    assert _day_offset("2026-07-01", days=1) == "2026-06-30"


def test_task_run_range_start_uses_inclusive_utc_days() -> None:
    assert _task_run_range_start("today", "2026-07-22") == 1_784_678_400
    assert _task_run_range_start("7d", "2026-07-22") == 1_784_160_000
    assert _task_run_range_start("30d", "2026-07-22") == 1_782_172_800
    assert _task_run_range_start("all", "2026-07-22") is None


def test_session_cost_priced() -> None:
    assert _session_cost({"total_cost_usd": 2.5}) == 2.5


def test_session_cost_unpriced_or_malformed() -> None:
    # Absent key (unpriced) and malformed values both read as 0.0.
    assert _session_cost({}) == 0.0
    assert _session_cost({"total_cost_usd": "oops"}) == 0.0
    assert _session_priced({"total_cost_usd": 0}) is True
    assert _session_priced({}) is False
    assert _session_priced({"total_cost_usd": "oops"}) is False


def test_usage_count_handles_missing_malformed_and_negative_values() -> None:
    assert _usage_count({"total_tokens": 123}, "total_tokens") == 123
    assert _usage_count({}, "total_tokens") == 0
    assert _usage_count({"total_tokens": "oops"}, "total_tokens") == 0
    assert _usage_count({"total_tokens": -1}, "total_tokens") == 0


def test_session_models_faithful_no_collapse() -> None:
    # Per-model costs are projected verbatim — no alias collapsing, no
    # requirement that they sum to the session total (matches the web UI).
    usage = {
        "total_cost_usd": 14.03,
        "by_model": {
            "system.ai.claude-opus-4-8[1m]": {"total_cost_usd": 14.03},
            "system.ai.claude-sonnet-4-6[1m]": {"total_cost_usd": 12.36},
        },
    }
    assert _session_models(usage) == {
        "system.ai.claude-opus-4-8[1m]": 14.03,
        "system.ai.claude-sonnet-4-6[1m]": 12.36,
    }


def test_session_models_omits_unpriced_and_malformed() -> None:
    usage = {
        "by_model": {
            "claude-opus-4-8": {"total_cost_usd": 1.0},
            "unpriced-model": {"input_tokens": 100},  # no cost key -> omitted
            "bad-model": {"total_cost_usd": "nan-ish"},  # malformed -> omitted
        }
    }
    assert _session_models(usage) == {"claude-opus-4-8": 1.0}


@pytest.mark.parametrize("value", [None, {}, "not-a-dict", 5])
def test_session_models_missing(value: object) -> None:
    assert _session_models({"by_model": value}) == {}
    assert _session_models({}) == {}


def _add_session(
    store: SqlAlchemyConversationStore,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ts: int,
    cost: float,
    by_model: dict[str, dict[str, float]],
    title: str,
    token_usage: dict[str, int] | None = None,
) -> str:
    # create_conversation stamps updated_at from now_epoch; pin it so the
    # session lands at a specific time. set_session_usage does not touch it.
    monkeypatch.setattr(
        "omnigent.stores.conversation_store.sqlalchemy_store.now_epoch",
        lambda: ts,
    )
    conv = store.create_conversation(
        title=title,
        agent_id=_AGENT_ID,
        agent_bundle_version=1,
        agent_bundle_digest=_BUNDLE_DIGEST,
        agent_bundle_location=f"bundles/{_BUNDLE_DIGEST}",
    )
    store.set_session_usage(
        conv.id,
        {"total_cost_usd": cost, "by_model": by_model, **(token_usage or {})},
    )
    return conv.id


def test_build_usage_report_summary_from_daily_rollup(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    # The summary windows are sourced from the per-user daily rollup, NOT from
    # each session's last-activity time — so record spend directly on the
    # rollup, attributed to calendar days relative to "today".
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-07-22", 1.0)  # today
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-07-18", 2.0)  # within 7d
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-07-01", 4.0)  # within 30d
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-05-01", 8.0)  # older, all-time only

    # 1_784_678_400 == 2026-07-22T00:00:00Z. usage._utc_today reads now_epoch
    # from omnigent.db.utils, so patch it there.
    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: 1_784_678_400)
    report = _build_usage_report(store, None)

    assert report.cost_today == 1.0
    assert report.cost_last_7d == 3.0  # today + 2026-07-18
    assert report.cost_last_30d == 7.0  # + 2026-07-01
    assert report.total_cost_usd == 15.0  # + 2026-05-01
    assert [(point.day_utc, point.cost_usd) for point in report.daily_cost] == [
        ("2026-05-01", 8.0),
        ("2026-07-01", 4.0),
        ("2026-07-18", 2.0),
        ("2026-07-22", 1.0),
    ]


def test_daily_cost_trend_fills_zero_days_for_selected_range(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-07-18", 2.0)
    store.add_daily_cost(RESERVED_USER_LOCAL, "2026-07-22", 1.0)
    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: 1_784_678_400)

    report = _build_usage_report(store, None, time_range="7d")

    assert len(report.daily_cost) == 7
    assert report.daily_cost[0].day_utc == "2026-07-16"
    assert report.daily_cost[-1].day_utc == "2026-07-22"
    assert sum(point.cost_usd for point in report.daily_cost) == 3.0


def test_build_usage_report_sessions_detail(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    now = 1_700_000_000

    recent = _add_session(
        store,
        monkeypatch,
        ts=now - 3600,
        cost=1.0,
        by_model={"claude-opus-4-8": {"total_cost_usd": 1.0}},
        title="recent",
        token_usage={
            "input_tokens": 700,
            "output_tokens": 300,
            "cache_read_input_tokens": 100,
            "total_tokens": 1100,
        },
    )
    older = _add_session(
        store,
        monkeypatch,
        ts=now - 3 * _DAY,
        cost=6.02,
        # Multi-model session whose per-model costs deliberately do NOT sum to
        # the session total (native cumulative attribution) — shown faithfully.
        by_model={
            "claude-opus-4-8": {"total_cost_usd": 6.02},
            "system.ai.claude-opus-4-8[1m]": {"total_cost_usd": 13.58},
        },
        title="older",
    )

    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: now)
    report = _build_usage_report(store, None)

    # Newest activity first; authoritative session cost + faithful per-model map.
    assert [s.id for s in report.sessions] == [recent, older]
    assert [s.cost_usd for s in report.sessions] == [1.0, 6.02]
    assert report.sessions[0].models == {"claude-opus-4-8": 1.0}
    assert report.sessions[0].input_tokens == 700
    assert report.sessions[0].output_tokens == 300
    assert report.sessions[0].cache_read_input_tokens == 100
    assert report.sessions[0].total_tokens == 1100
    assert report.sessions[1].models == {
        "claude-opus-4-8": 6.02,
        "system.ai.claude-opus-4-8[1m]": 13.58,
    }


def test_build_usage_report_empty(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    report = _build_usage_report(store, None)
    assert report.sessions == []
    assert report.cost_today == 0.0
    assert report.cost_last_7d == 0.0
    assert report.cost_last_30d == 0.0
    assert report.total_cost_usd == 0.0


def test_build_usage_report_unpriced_session(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    now = 1_700_000_000
    monkeypatch.setattr(
        "omnigent.stores.conversation_store.sqlalchemy_store.now_epoch",
        lambda: now,
    )
    # A session with no recorded usage: cost falls back to 0.0, no models.
    conv = store.create_conversation(
        title="bare",
        agent_id=_AGENT_ID,
        agent_bundle_version=1,
        agent_bundle_digest=_BUNDLE_DIGEST,
        agent_bundle_location=f"bundles/{_BUNDLE_DIGEST}",
    )

    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: now)
    report = _build_usage_report(store, None)

    bare = next(s for s in report.sessions if s.id == conv.id)
    assert bare.cost_usd == 0.0
    assert bare.priced is False
    assert bare.models == {}


def _usage_run(
    run_id: str,
    *,
    state: TaskRunState,
    session_id: str | None,
    queued_at: int,
    started_at: int | None,
    finished_at: int | None,
    trigger: TaskRunTrigger = TaskRunTrigger.MANUAL,
    retry_of_run_id: str | None = None,
) -> WorkItemRun:
    return WorkItemRun(
        id=run_id,
        work_item_id="task-advanced",
        owner_user_id="alice",
        session_id=session_id,
        agent_id="agent-polly",
        runtime_id="runtime-mac",
        workspace="/tmp/work",
        state=state,
        trigger=trigger,
        retry_of_run_id=retry_of_run_id,
        queued_at=queued_at,
        started_at=started_at,
        finished_at=finished_at,
        updated_at=finished_at or started_at,
        result_summary=None,
        failure_code="runner_error" if state is TaskRunState.FAILED else None,
        failure_message="Runner stopped" if state is TaskRunState.FAILED else None,
        failure_retryable=state is TaskRunState.FAILED,
    )


def test_advanced_usage_aggregates_task_runs_and_explicit_data_gaps(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    priced_session = _add_session(
        store,
        monkeypatch,
        ts=100,
        cost=1.25,
        by_model={"gpt-5.6": {"total_cost_usd": 1.25}},
        title="priced run",
        token_usage={"input_tokens": 800, "output_tokens": 200, "total_tokens": 1000},
    )
    waiting_session = _add_session(
        store,
        monkeypatch,
        ts=200,
        cost=0,
        by_model={},
        title="waiting run",
        token_usage={"total_tokens": 50},
    )
    store.set_session_usage(waiting_session, {"total_tokens": 50})
    store.set_session_state(waiting_session, {"waiting_reason": "Awaiting approval"})
    store.append(
        priced_session,
        [
            NewConversationItem(
                type="function_call",
                response_id="response-1",
                data=FunctionCallData(
                    agent="polly",
                    name="load_skill",
                    arguments='{"name":"cross-review"}',
                    call_id="call-1",
                ),
            )
        ],
    )

    task = WorkItem(
        id="task-advanced",
        owner_user_id="alice",
        title="Ship advanced usage",
        description=None,
        state=TaskState.IN_PROGRESS,
        priority="high",
        project_id="project-launch",
        assignee_agent_id="agent-polly",
        due_at=None,
        created_at=1,
        updated_at=2,
        completed_at=None,
        version=1,
    )
    runs = [
        _usage_run(
            "run-success",
            state=TaskRunState.SUCCEEDED,
            session_id=priced_session,
            queued_at=10,
            started_at=15,
            finished_at=45,
        ),
        _usage_run(
            "run-failed",
            state=TaskRunState.FAILED,
            session_id=None,
            queued_at=50,
            started_at=60,
            finished_at=80,
            trigger=TaskRunTrigger.RETRY,
            retry_of_run_id="run-success",
        ),
        _usage_run(
            "run-cancelled",
            state=TaskRunState.CANCELLED,
            session_id=None,
            queued_at=90,
            started_at=None,
            finished_at=95,
        ),
        _usage_run(
            "run-waiting",
            state=TaskRunState.WAITING,
            session_id=waiting_session,
            queued_at=100,
            started_at=110,
            finished_at=None,
        ),
    ]
    owner_calls: list[str | None] = []

    class WorkItems:
        def list(self, *, owner_user_id: str | None):
            owner_calls.append(owner_user_id)
            return [task] if owner_user_id == "alice" else []

    class Runs:
        def list_for_work_item(self, work_item_id: str, *, owner_user_id: str | None):
            assert work_item_id == task.id
            assert owner_user_id == "alice"
            return runs

    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: 200)
    report = _build_usage_report(
        store,
        "alice",
        work_item_store=WorkItems(),
        work_item_run_store=Runs(),
        project_store=SimpleNamespace(
            list=lambda **_: [
                Project(
                    id="project-launch",
                    name="Launch",
                    owner_user_id="alice",
                    created_at=1,
                )
            ]
        ),
        agent_store=SimpleNamespace(get_names=lambda ids: dict.fromkeys(ids, "Polly")),
        host_store=SimpleNamespace(
            list_hosts=lambda user_id: [
                SimpleNamespace(host_id="runtime-mac", name="MacBook Pro", user_id=user_id)
            ]
        ),
    )

    assert owner_calls == ["alice"]
    assert report.operations.total_tasks == 1
    assert report.operations.total_runs == 4
    assert report.operations.active_runs == 1
    assert report.operations.terminal_runs == 3
    assert report.operations.succeeded_runs == 1
    assert report.operations.failed_runs == 1
    assert report.operations.cancelled_runs == 1
    assert report.operations.waiting_runs == 1
    assert report.operations.success_rate == pytest.approx(1 / 3, abs=0.0001)
    assert report.operations.retry_runs == 1
    assert report.operations.retry_rate == 0.25
    assert report.operations.average_queue_seconds == pytest.approx(25 / 3, abs=0.01)
    assert report.operations.average_run_seconds == 25
    assert report.operations.priced_runs == 1
    assert report.operations.unpriced_runs == 3
    assert report.operations.waiting_duration_available is False

    project = report.breakdowns.projects[0]
    assert (project.name, project.run_count, project.success_rate) == (
        "Launch",
        4,
        pytest.approx(1 / 3, abs=0.0001),
    )
    assert project.cost_usd == 1.25
    assert report.breakdowns.agents[0].name == "Polly"
    assert report.breakdowns.runtimes[0].name == "MacBook Pro"
    skill = report.breakdowns.skills[0]
    assert (skill.name, skill.run_count, skill.uses) == ("cross-review", 1, 1)
    assert skill.cost_attribution == "session_association_only"

    success = next(row for row in report.task_runs if row.id == "run-success")
    waiting = next(row for row in report.task_runs if row.id == "run-waiting")
    failed = next(row for row in report.task_runs if row.id == "run-failed")
    assert success.priced is True
    assert success.cost_usd == 1.25
    assert success.total_tokens == 1000
    assert success.observed_skills == ["cross-review"]
    assert waiting.priced is False
    assert waiting.run_duration_live is True
    assert waiting.run_seconds == 90
    assert waiting.waiting_reason == "Awaiting approval"
    assert failed.session_id is None
    assert failed.failure_message == "Runner stopped"


def test_advanced_usage_success_and_retry_rates_are_null_without_samples(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    task = WorkItem(
        id="task-queued",
        owner_user_id=None,
        title="Queued",
        description=None,
        state=TaskState.TODO,
        priority="medium",
        project_id=None,
        assignee_agent_id="agent-1",
        due_at=None,
        created_at=1,
        updated_at=None,
        completed_at=None,
        version=1,
    )
    queued = _usage_run(
        "run-queued",
        state=TaskRunState.QUEUED,
        session_id=None,
        queued_at=10,
        started_at=None,
        finished_at=None,
    )
    queued.owner_user_id = None
    queued.work_item_id = task.id
    report = _build_usage_report(
        store,
        None,
        work_item_store=SimpleNamespace(list=lambda **_: [task]),
        work_item_run_store=SimpleNamespace(list_for_work_item=lambda *_args, **_kwargs: [queued]),
    )
    assert report.operations.success_rate is None
    assert report.operations.retry_rate == 0
    assert report.operations.average_queue_seconds is None
    assert report.operations.average_run_seconds is None


def test_advanced_usage_filters_task_runs_and_preserves_filter_options(
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    today_start = 1_784_678_400
    tasks = [
        WorkItem(
            id=f"task-{index}",
            owner_user_id="alice",
            title=f"Task {index}",
            description=None,
            state=TaskState.IN_PROGRESS,
            priority="medium",
            project_id=f"project-{index}",
            assignee_agent_id=f"agent-{index}",
            due_at=None,
            created_at=1,
            updated_at=2,
            completed_at=None,
            version=1,
        )
        for index in (1, 2)
    ]
    recent = _usage_run(
        "run-recent",
        state=TaskRunState.SUCCEEDED,
        session_id=None,
        queued_at=today_start + 10,
        started_at=today_start + 15,
        finished_at=today_start + 20,
    )
    recent.work_item_id = tasks[0].id
    recent.agent_id = "agent-1"
    old = _usage_run(
        "run-old",
        state=TaskRunState.FAILED,
        session_id=None,
        queued_at=today_start - _DAY,
        started_at=today_start - _DAY + 5,
        finished_at=today_start - _DAY + 10,
    )
    old.work_item_id = tasks[1].id
    old.agent_id = "agent-2"
    runs = {tasks[0].id: [recent], tasks[1].id: [old]}
    monkeypatch.setattr("omnigent.db.utils.now_epoch", lambda: today_start + 100)

    report = _build_usage_report(
        store,
        "alice",
        work_item_store=SimpleNamespace(list=lambda **_: tasks),
        work_item_run_store=SimpleNamespace(
            list_for_work_item=lambda work_item_id, **_: runs[work_item_id]
        ),
        project_store=SimpleNamespace(
            list=lambda **_: [
                Project(
                    id=f"project-{index}",
                    name=f"Project {index}",
                    owner_user_id="alice",
                    created_at=1,
                )
                for index in (1, 2)
            ]
        ),
        agent_store=SimpleNamespace(
            get_names=lambda ids: {value: value.replace("agent", "Agent") for value in ids}
        ),
        time_range="today",
        project_id="project-1",
        agent_id="agent-1",
    )

    assert [row.id for row in report.task_runs] == ["run-recent"]
    assert report.operations.total_tasks == 1
    assert report.operations.total_runs == 1
    assert [option.id for option in report.filter_options.projects] == [
        "project-1",
        "project-2",
    ]
    assert [option.id for option in report.filter_options.agents] == ["agent-1", "agent-2"]


def test_sum_daily_cost_range(db_uri: str) -> None:
    store = SqlAlchemyConversationStore(db_uri)
    store.add_daily_cost("alice", "2026-07-01", 1.0)
    store.add_daily_cost("alice", "2026-07-10", 2.0)
    store.add_daily_cost("alice", "2026-07-20", 4.0)
    store.add_daily_cost("bob", "2026-07-20", 100.0)  # other user, excluded

    assert store.sum_daily_cost("alice", "2026-07-10") == 6.0  # 10th + 20th
    assert store.sum_daily_cost("alice", "0000-00-00") == 7.0  # all-time
    assert store.sum_daily_cost("alice", "2026-08-01") == 0.0  # nothing in range
    assert store.sum_daily_cost("nobody", "0000-00-00") == 0.0
