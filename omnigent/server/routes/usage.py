"""API route for the per-user LLM cost report (``omni usage``)."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request

from omnigent.entities import FunctionCallData
from omnigent.runtime.policies.builder import load_session_usage
from omnigent.server.auth import RESERVED_USER_LOCAL, AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.server.schemas import (
    DailyCostUsage,
    OperationalUsageMetrics,
    SessionUsage,
    TaskRunUsage,
    UsageBreakdownRow,
    UsageBreakdowns,
    UsageFilterOption,
    UsageFilterOptions,
    UsageReport,
)
from omnigent.stores import ConversationStore
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.project_store import ProjectStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore

# The daily rollup floor for an "all-time" sum: earlier than any real row, so
# ``sum_daily_cost`` with this lower bound totals every recorded day.
_EPOCH_DAY = "0000-00-00"
_ACTIVE_STATES = {"queued", "running", "waiting"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
UsageTimeRange = Literal["today", "7d", "30d", "all"]


def _utc_today() -> str:
    """Return the current UTC calendar day as ``"YYYY-MM-DD"``."""
    from omnigent.db.utils import now_epoch

    return datetime.fromtimestamp(now_epoch(), tz=timezone.utc).date().isoformat()


def _day_offset(day_utc: str, *, days: int) -> str:
    """Return the UTC day *days* before *day_utc*, as ``"YYYY-MM-DD"``."""
    base = datetime.strptime(day_utc, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (base - timedelta(days=days)).date().isoformat()


def _task_run_range_start(time_range: UsageTimeRange, today_utc: str) -> int | None:
    """Return the inclusive UTC-day lower bound for a TaskRun range."""
    if time_range == "all":
        return None
    days = {"today": 0, "7d": 6, "30d": 29}[time_range]
    start_day = _day_offset(today_utc, days=days)
    return int(datetime.strptime(start_day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _daily_cost_points(
    conversation_store: ConversationStore,
    user_id: str,
    time_range: UsageTimeRange,
    today_utc: str,
) -> list[DailyCostUsage]:
    """Build an authoritative daily cost series, filling selected range gaps."""
    if time_range == "all":
        return [
            DailyCostUsage(day_utc=day, cost_usd=cost)
            for day, cost in conversation_store.list_daily_costs(user_id, _EPOCH_DAY)
        ]
    days = {"today": 0, "7d": 6, "30d": 29}[time_range]
    since = _day_offset(today_utc, days=days)
    recorded = dict(conversation_store.list_daily_costs(user_id, since))
    start = datetime.strptime(since, "%Y-%m-%d").date()
    return [
        DailyCostUsage(
            day_utc=(start + timedelta(days=offset)).isoformat(),
            cost_usd=recorded.get((start + timedelta(days=offset)).isoformat(), 0.0),
        )
        for offset in range(days + 1)
    ]


def _session_models(usage: dict[str, Any]) -> dict[str, float]:
    """
    Project a session's ``by_model`` map into a ``{model_id: cost_usd}`` dict.

    Mirrors the web session sidebar's per-model list: each model's recorded
    cost, keyed by the raw harness model id, shown faithfully. Models with no
    recorded cost are omitted. NOT guaranteed to sum to the session's
    ``total_cost_usd`` — see :class:`SessionUsage`.

    :param usage: A subtree-summed ``session_usage`` dict.
    :returns: Per-model cost map (empty when no per-model cost was recorded).
    """
    by_model = usage.get("by_model")
    if not isinstance(by_model, dict):
        return {}
    models: dict[str, float] = {}
    for name, bucket in by_model.items():
        if not isinstance(bucket, dict) or "total_cost_usd" not in bucket:
            continue
        try:
            models[str(name)] = float(bucket["total_cost_usd"])
        except (TypeError, ValueError):
            continue
    return models


def _session_cost(usage: dict[str, Any]) -> float:
    """
    Read a session's authoritative cumulative cost, or ``0.0`` when unpriced.

    ``total_cost_usd`` is present only on priced sessions (the "priced ⟺ key
    present" contract); an absent or malformed value reads as ``0.0``.
    """
    if "total_cost_usd" not in usage:
        return 0.0
    try:
        return float(usage["total_cost_usd"])
    except (TypeError, ValueError):
        return 0.0


def _session_priced(usage: dict[str, Any]) -> bool:
    """Return whether the authoritative session cost was actually recorded."""
    if "total_cost_usd" not in usage:
        return False
    try:
        float(usage["total_cost_usd"])
    except (TypeError, ValueError):
        return False
    return True


def _usage_count(usage: dict[str, Any], key: str) -> int:
    """Read a non-negative cumulative token counter from ``usage``."""
    try:
        value = int(usage.get(key, 0))
    except (TypeError, ValueError):
        return 0
    return max(value, 0)


def _loaded_skills(conversation_store: ConversationStore, session_id: str) -> Counter[str]:
    """Count observed ``load_skill`` calls for one TaskRun Session."""
    counts: Counter[str] = Counter()
    after: str | None = None
    while True:
        page = conversation_store.list_items(
            session_id,
            limit=1000,
            after=after,
            order="asc",
            type="function_call",
        )
        for item in page.data:
            data = item.data
            if not isinstance(data, FunctionCallData) or data.name != "load_skill":
                continue
            try:
                arguments = json.loads(data.arguments)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(arguments, dict):
                continue
            name = arguments.get("name")
            if not isinstance(name, str):
                name = arguments.get("skill_name")
            if isinstance(name, str) and name.strip():
                counts[name.strip()] += 1
        if not page.has_more or page.last_id is None:
            break
        after = page.last_id
    return counts


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _add_breakdown_run(
    aggregates: dict[str, dict[str, Any]],
    *,
    row_id: str,
    name: str,
    state: str,
    priced: bool,
    cost_usd: float,
    total_tokens: int,
    run_seconds: float | None,
    uses: int | None = None,
    cost_attribution: str = "session",
) -> None:
    row = aggregates.setdefault(
        row_id,
        {
            "id": row_id,
            "name": name,
            "run_count": 0,
            "succeeded_runs": 0,
            "failed_runs": 0,
            "terminal_runs": 0,
            "cost_usd": 0.0,
            "priced_run_count": 0,
            "unpriced_run_count": 0,
            "total_tokens": 0,
            "run_durations": [],
            "uses": 0 if uses is not None else None,
            "cost_attribution": cost_attribution,
        },
    )
    row["run_count"] += 1
    row["succeeded_runs"] += state == "succeeded"
    row["failed_runs"] += state == "failed"
    row["terminal_runs"] += state in _TERMINAL_STATES
    row["priced_run_count"] += priced
    row["unpriced_run_count"] += not priced
    if priced:
        row["cost_usd"] += cost_usd
    row["total_tokens"] += total_tokens
    if run_seconds is not None:
        row["run_durations"].append(run_seconds)
    if uses is not None:
        row["uses"] += uses


def _breakdown_rows(aggregates: dict[str, dict[str, Any]]) -> list[UsageBreakdownRow]:
    rows: list[UsageBreakdownRow] = []
    for aggregate in aggregates.values():
        terminal_runs = aggregate.pop("terminal_runs")
        durations = aggregate.pop("run_durations")
        succeeded_runs = aggregate["succeeded_runs"]
        rows.append(
            UsageBreakdownRow(
                **aggregate,
                success_rate=(round(succeeded_runs / terminal_runs, 4) if terminal_runs else None),
                average_run_seconds=_mean(durations),
            )
        )
    return sorted(rows, key=lambda row: (-row.run_count, row.name.casefold(), row.id))


def _build_usage_report(
    conversation_store: ConversationStore,
    user_id: str | None,
    *,
    work_item_store: WorkItemStore | None = None,
    work_item_run_store: WorkItemRunStore | None = None,
    project_store: ProjectStore | None = None,
    agent_store: AgentStore | None = None,
    host_store: HostStore | None = None,
    time_range: UsageTimeRange = "all",
    project_id: str | None = None,
    agent_id: str | None = None,
) -> UsageReport:
    """
    Build the usage report: a daily-rollup cost summary plus session detail.

    The summary (today / last 7 days / last 30 days / all-time) is summed
    from the per-user daily-cost rollup (``user_daily_cost``), which
    attributes spend to the UTC day it occurred on — so the windows reflect
    when spend actually happened, not merely a session's last-activity time.

    The per-session detail is a separate view over each top-level session's
    cumulative ``session_usage`` (rolled up across its sub-agent subtree via
    :func:`load_session_usage`), newest activity first, carrying the
    authoritative session cost and the per-model breakdown.

    :param conversation_store: Store to read the rollup and sessions from.
    :param user_id: The caller / ACL scope. ``None`` in single-user mode maps
        to the reserved local owner the daily rollup and grants are keyed by.
    :returns: The populated :class:`UsageReport`.
    """
    # The daily rollup and session-permission grants key spend by the resolved
    # owner, which is the reserved local sentinel in single-user mode (where
    # require_user yields None). Map None -> "local" so the summary reads the
    # same rows the write path recorded.
    rollup_user = user_id if user_id is not None else RESERVED_USER_LOCAL

    today = _utc_today()
    cost_today = conversation_store.sum_daily_cost(rollup_user, today)
    cost_7d = conversation_store.sum_daily_cost(rollup_user, _day_offset(today, days=6))
    cost_30d = conversation_store.sum_daily_cost(rollup_user, _day_offset(today, days=29))
    total = conversation_store.sum_daily_cost(rollup_user, _EPOCH_DAY)
    daily_cost = _daily_cost_points(conversation_store, rollup_user, time_range, today)

    sessions: list[SessionUsage] = []
    session_usage: dict[str, dict[str, Any]] = {}
    after: str | None = None
    while True:
        page = conversation_store.list_conversations(
            limit=200,
            after=after,
            accessible_by=user_id,
            has_agent_id=True,
            kind="default",
            order="desc",
            sort_by="updated_at",
        )
        for conv in page.data:
            if conv.agent_id is None:
                continue
            usage = load_session_usage(conv.id, conversation_store)
            session_usage[conv.id] = usage
            sessions.append(
                SessionUsage(
                    id=conv.id,
                    created_at=conv.created_at,
                    updated_at=conv.updated_at,
                    title=conv.title,
                    cost_usd=_session_cost(usage),
                    priced=_session_priced(usage),
                    input_tokens=_usage_count(usage, "input_tokens"),
                    output_tokens=_usage_count(usage, "output_tokens"),
                    cache_read_input_tokens=_usage_count(usage, "cache_read_input_tokens"),
                    total_tokens=_usage_count(usage, "total_tokens"),
                    models=_session_models(usage),
                )
            )
        if not page.has_more:
            break
        after = page.last_id

    if work_item_store is None or work_item_run_store is None:
        return UsageReport(
            cost_today=cost_today,
            cost_last_7d=cost_7d,
            cost_last_30d=cost_30d,
            total_cost_usd=total,
            daily_cost=daily_cost,
            sessions=sessions,
        )

    from omnigent.db.utils import now_epoch

    tasks = work_item_store.list(owner_user_id=user_id)
    all_runs = [
        (task, run)
        for task in tasks
        for run in work_item_run_store.list_for_work_item(task.id, owner_user_id=user_id)
    ]
    projects = {
        project.id: project
        for project in (project_store.list(owner_user_id=user_id) if project_store else [])
    }
    agent_names = (
        agent_store.get_names(list({run.agent_id for _, run in all_runs})) if agent_store else {}
    )
    filter_options = UsageFilterOptions(
        projects=[
            UsageFilterOption(
                id=value,
                name=projects[value].name if value in projects else value,
            )
            for value in sorted(
                {task.project_id for task, _ in all_runs if task.project_id is not None},
                key=lambda value: (
                    projects[value].name.casefold() if value in projects else value.casefold(),
                    value,
                ),
            )
        ],
        agents=[
            UsageFilterOption(id=value, name=agent_names.get(value, value))
            for value in sorted(
                {run.agent_id for _, run in all_runs},
                key=lambda value: (agent_names.get(value, value).casefold(), value),
            )
        ],
    )
    range_start = _task_run_range_start(time_range, today)
    runs = [
        (task, run)
        for task, run in all_runs
        if (range_start is None or run.queued_at >= range_start)
        and (project_id is None or task.project_id == project_id)
        and (agent_id is None or run.agent_id == agent_id)
    ]
    runs.sort(key=lambda pair: (pair[1].queued_at, pair[1].id), reverse=True)
    conversations = conversation_store.get_conversations(
        [run.session_id for _, run in runs if run.session_id is not None]
    )
    host_names = {
        host.host_id: host.name
        for host in (
            host_store.list_hosts(user_id if user_id is not None else RESERVED_USER_LOCAL)
            if host_store
            else []
        )
    }

    project_aggregates: dict[str, dict[str, Any]] = {}
    agent_aggregates: dict[str, dict[str, Any]] = {}
    runtime_aggregates: dict[str, dict[str, Any]] = {}
    skill_aggregates: dict[str, dict[str, Any]] = {}
    task_run_rows: list[TaskRunUsage] = []
    queue_durations: list[float] = []
    completed_durations: list[float] = []
    now = now_epoch()

    for task, run in runs:
        state = run.state.value
        trigger = run.trigger.value
        conversation = conversations.get(run.session_id) if run.session_id else None
        usage: dict[str, Any] = {}
        skill_counts: Counter[str] = Counter()
        if run.session_id is not None and conversation is not None:
            usage = session_usage.get(run.session_id, {})
            if run.session_id not in session_usage:
                usage = load_session_usage(run.session_id, conversation_store)
                session_usage[run.session_id] = usage
            skill_counts = _loaded_skills(conversation_store, run.session_id)

        priced = _session_priced(usage)
        cost_usd = _session_cost(usage)
        input_tokens = _usage_count(usage, "input_tokens")
        output_tokens = _usage_count(usage, "output_tokens")
        cache_tokens = _usage_count(usage, "cache_read_input_tokens")
        total_tokens = _usage_count(usage, "total_tokens")
        queue_seconds = (
            float(max(run.started_at - run.queued_at, 0)) if run.started_at is not None else None
        )
        finished_run_seconds = (
            float(max(run.finished_at - run.started_at, 0))
            if run.started_at is not None and run.finished_at is not None
            else None
        )
        duration_live = (
            run.started_at is not None
            and run.finished_at is None
            and state in {"running", "waiting"}
        )
        run_seconds = (
            float(max(now - run.started_at, 0))
            if duration_live and run.started_at is not None
            else finished_run_seconds
        )
        if queue_seconds is not None:
            queue_durations.append(queue_seconds)
        if finished_run_seconds is not None:
            completed_durations.append(finished_run_seconds)

        project = projects.get(task.project_id) if task.project_id else None
        agent_name = agent_names.get(run.agent_id, run.agent_id)
        runtime_name = host_names.get(run.runtime_id, run.runtime_id)
        waiting_reason = None
        if state == "waiting" and conversation is not None:
            value = conversation.session_state.get("waiting_reason")
            waiting_reason = value if isinstance(value, str) and value else None

        task_run_rows.append(
            TaskRunUsage(
                id=run.id,
                task_id=task.id,
                task_title=task.title,
                project_id=task.project_id,
                project_name=project.name if project else None,
                agent_id=run.agent_id,
                agent_name=agent_name,
                runtime_id=run.runtime_id,
                runtime_name=runtime_name,
                session_id=run.session_id,
                state=state,
                trigger=trigger,
                retry_of_run_id=run.retry_of_run_id,
                queued_at=run.queued_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
                queue_seconds=queue_seconds,
                run_seconds=run_seconds,
                run_duration_live=duration_live,
                priced=priced,
                cost_usd=cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_tokens,
                total_tokens=total_tokens,
                observed_skills=sorted(skill_counts),
                waiting_reason=waiting_reason,
                failure_code=run.failure_code,
                failure_message=run.failure_message,
            )
        )

        common = {
            "state": state,
            "priced": priced,
            "cost_usd": cost_usd,
            "total_tokens": total_tokens,
            "run_seconds": finished_run_seconds,
        }
        if task.project_id is not None:
            _add_breakdown_run(
                project_aggregates,
                row_id=task.project_id,
                name=project.name if project else task.project_id,
                **common,
            )
        _add_breakdown_run(
            agent_aggregates,
            row_id=run.agent_id,
            name=agent_name,
            **common,
        )
        _add_breakdown_run(
            runtime_aggregates,
            row_id=run.runtime_id,
            name=runtime_name,
            **common,
        )
        for skill_name, uses in skill_counts.items():
            _add_breakdown_run(
                skill_aggregates,
                row_id=skill_name,
                name=skill_name,
                uses=uses,
                cost_attribution="session_association_only",
                **common,
            )

    terminal_runs = [run for _, run in runs if run.state.value in _TERMINAL_STATES]
    succeeded_runs = sum(run.state.value == "succeeded" for run in terminal_runs)
    retry_runs = sum(
        run.retry_of_run_id is not None or run.trigger.value == "retry" for _, run in runs
    )
    priced_runs = sum(row.priced for row in task_run_rows)

    return UsageReport(
        cost_today=cost_today,
        cost_last_7d=cost_7d,
        cost_last_30d=cost_30d,
        total_cost_usd=total,
        daily_cost=daily_cost,
        sessions=sessions,
        operations=OperationalUsageMetrics(
            total_tasks=len({task.id for task, _ in runs}),
            total_runs=len(runs),
            active_runs=sum(run.state.value in _ACTIVE_STATES for _, run in runs),
            terminal_runs=len(terminal_runs),
            succeeded_runs=succeeded_runs,
            failed_runs=sum(run.state.value == "failed" for run in terminal_runs),
            cancelled_runs=sum(run.state.value == "cancelled" for run in terminal_runs),
            waiting_runs=sum(run.state.value == "waiting" for _, run in runs),
            success_rate=(
                round(succeeded_runs / len(terminal_runs), 4) if terminal_runs else None
            ),
            retry_runs=retry_runs,
            retry_rate=round(retry_runs / len(runs), 4) if runs else None,
            average_queue_seconds=_mean(queue_durations),
            average_run_seconds=_mean(completed_durations),
            priced_runs=priced_runs,
            unpriced_runs=len(runs) - priced_runs,
            waiting_duration_available=False,
        ),
        breakdowns=UsageBreakdowns(
            projects=_breakdown_rows(project_aggregates),
            agents=_breakdown_rows(agent_aggregates),
            runtimes=_breakdown_rows(runtime_aggregates),
            skills=_breakdown_rows(skill_aggregates),
        ),
        filter_options=filter_options,
        task_runs=task_run_rows,
    )


def create_usage_router(
    conversation_store: ConversationStore,
    *,
    work_item_store: WorkItemStore | None = None,
    work_item_run_store: WorkItemRunStore | None = None,
    project_store: ProjectStore | None = None,
    agent_store: AgentStore | None = None,
    host_store: HostStore | None = None,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """
    Create the per-user usage-report router.

    The report is user-scoped, not session-scoped, so it lives in its own
    router rather than under the sessions router.

    :param conversation_store: Store for the daily rollup and session reads.
    :param auth_provider: Auth provider for user identity. ``None`` disables
        auth (single-user / local mode).
    :returns: The configured router (mounted under ``/v1``).
    """
    router = APIRouter()

    @router.get("/usage", response_model=UsageReport)
    async def get_usage(
        request: Request,
        time_range: Annotated[UsageTimeRange, Query(alias="range")] = "all",
        project_id: str | None = None,
        agent_id: str | None = None,
    ) -> UsageReport:
        """
        Aggregate the calling user's LLM spend across their sessions.

        require_user, not get_user_id: the aggregation scopes to the caller,
        so a request slipping through as ``None`` in multi-user mode would
        read another scope. Fail closed with 401 instead (``user_id`` is
        ``None`` only when auth is disabled — the single-user / local case).
        """
        user_id = require_user(request, auth_provider)
        return await asyncio.to_thread(
            _build_usage_report,
            conversation_store,
            user_id,
            work_item_store=work_item_store,
            work_item_run_store=work_item_run_store,
            project_store=project_store,
            agent_store=agent_store,
            host_store=host_store,
            time_range=time_range,
            project_id=project_id,
            agent_id=agent_id,
        )

    return router
