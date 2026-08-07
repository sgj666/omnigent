"""Owner-scoped operational activity for Agent Bundle detail pages."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from omnigent.entities import FunctionCallData
from omnigent.server.auth import AuthProvider
from omnigent.server.routes._auth_helpers import require_user
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.project_store import ProjectStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore

_ACTIVE_STATES = {"queued", "running", "waiting"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def _loaded_skills(conversation_store: ConversationStore, session_id: str) -> Counter[str]:
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
            name = arguments.get("name") if isinstance(arguments, dict) else None
            if not isinstance(name, str):
                name = arguments.get("skill_name") if isinstance(arguments, dict) else None
            if isinstance(name, str) and name.strip():
                counts[name.strip()] += 1
        if not page.has_more or page.last_id is None:
            break
        after = page.last_id
    return counts


def _build_activity(
    agent_id: str,
    *,
    owner_user_id: str | None,
    agent_store: AgentStore,
    conversation_store: ConversationStore,
    work_item_store: WorkItemStore,
    work_item_run_store: WorkItemRunStore,
    project_store: ProjectStore | None,
) -> dict[str, Any]:
    if agent_store.get(agent_id) is None:
        raise KeyError(agent_id)

    tasks = [
        task
        for task in work_item_store.list(owner_user_id=owner_user_id)
        if task.assignee_agent_id == agent_id
    ]
    projects = {
        project.id: project
        for project in (project_store.list(owner_user_id=owner_user_id) if project_store else [])
    }
    runs = [
        (task, run)
        for task in tasks
        for run in work_item_run_store.list_for_work_item(
            task.id,
            owner_user_id=owner_user_id,
        )
    ]
    runs.sort(key=lambda pair: (pair[1].queued_at, pair[1].id), reverse=True)
    sessions = conversation_store.get_conversations(
        [run.session_id for _, run in runs if run.session_id is not None]
    )

    skill_counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    project_run_counts: Counter[str] = Counter()
    for task, run in runs:
        state = run.state.value
        session = sessions.get(run.session_id) if run.session_id else None
        if run.session_id:
            skill_counts.update(_loaded_skills(conversation_store, run.session_id))
        if task.project_id:
            project_run_counts[task.project_id] += 1
        waiting_reason = None
        if state == "waiting" and session is not None:
            value = session.session_state.get("waiting_reason")
            waiting_reason = value if isinstance(value, str) and value else None
        rows.append(
            {
                "id": run.id,
                "task_id": task.id,
                "task_title": task.title,
                "state": state,
                "queued_at": run.queued_at,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "session_id": run.session_id,
                "runtime_id": run.runtime_id,
                "workspace": run.workspace,
                "project_id": task.project_id,
                "project_name": (
                    projects[task.project_id].name
                    if task.project_id is not None and task.project_id in projects
                    else None
                ),
                "waiting_reason": waiting_reason,
                "failure_code": run.failure_code,
                "failure_message": run.failure_message,
            }
        )

    terminal = [run for _, run in runs if run.state.value in _TERMINAL_STATES]
    succeeded = sum(run.state.value == "succeeded" for run in terminal)
    return {
        "agent_id": agent_id,
        "total_runs": len(runs),
        "active_runs": sum(run.state.value in _ACTIVE_STATES for _, run in runs),
        "waiting_runs": sum(run.state.value == "waiting" for _, run in runs),
        "failed_runs": sum(run.state.value == "failed" for _, run in runs),
        "success_rate": round(succeeded / len(terminal), 4) if terminal else None,
        "recent_runs": rows[:20],
        "projects": [
            {
                "id": project_id,
                "name": projects[project_id].name,
                "run_count": count,
            }
            for project_id, count in project_run_counts.most_common()
            if project_id in projects
        ],
        "skills": [
            {"name": name, "uses": uses}
            for name, uses in sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "skill_usage_source": "observed_load_skill_calls",
    }


def create_agent_activity_router(
    *,
    agent_store: AgentStore,
    conversation_store: ConversationStore,
    work_item_store: WorkItemStore,
    work_item_run_store: WorkItemRunStore,
    project_store: ProjectStore | None = None,
    auth_provider: AuthProvider | None = None,
) -> APIRouter:
    """Create the read-only Agent Activity endpoint."""
    router = APIRouter()

    @router.get("/agent-bundles/{agent_id}/activity")
    async def get_agent_activity(request: Request, agent_id: str) -> dict[str, Any]:
        owner_user_id = require_user(request, auth_provider)
        try:
            return await asyncio.to_thread(
                _build_activity,
                agent_id,
                owner_user_id=owner_user_id,
                agent_store=agent_store,
                conversation_store=conversation_store,
                work_item_store=work_item_store,
                work_item_run_store=work_item_run_store,
                project_store=project_store,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"code": "not_found"}) from None

    return router
