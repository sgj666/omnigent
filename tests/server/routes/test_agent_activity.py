from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from omnigent.entities import FunctionCallData, Project, WorkItem, WorkItemRun
from omnigent.server.routes.agent_activity import create_agent_activity_router
from omnigent.work_lifecycle import TaskRunState, TaskRunTrigger, TaskState


def _run(run_id: str, state: TaskRunState, session_id: str) -> WorkItemRun:
    return WorkItemRun(
        id=run_id,
        work_item_id="task-1",
        owner_user_id=None,
        session_id=session_id,
        agent_id="agent-1",
        runtime_id="host-1",
        workspace="/tmp/work",
        state=state,
        trigger=TaskRunTrigger.MANUAL,
        retry_of_run_id=None,
        queued_at={"run-ok": 30, "run-wait": 20, "run-fail": 10}[run_id],
        started_at=11,
        finished_at=31 if state in {TaskRunState.SUCCEEDED, TaskRunState.FAILED} else None,
        updated_at=31,
        result_summary=None,
        failure_code="runner_error" if state is TaskRunState.FAILED else None,
        failure_message="Runner stopped" if state is TaskRunState.FAILED else None,
        failure_retryable=state is TaskRunState.FAILED,
    )


def test_agent_activity_aggregates_runs_projects_and_observed_skills() -> None:
    task = WorkItem(
        id="task-1",
        owner_user_id=None,
        title="Ship report",
        description=None,
        state=TaskState.IN_PROGRESS,
        priority="high",
        project_id="project-1",
        assignee_agent_id="agent-1",
        due_at=None,
        created_at=1,
        updated_at=2,
        completed_at=None,
        version=1,
    )
    runs = [
        _run("run-ok", TaskRunState.SUCCEEDED, "session-ok"),
        _run("run-wait", TaskRunState.WAITING, "session-wait"),
        _run("run-fail", TaskRunState.FAILED, "session-fail"),
    ]

    class Conversations:
        def get_conversations(self, ids: list[str]):
            return {
                session_id: SimpleNamespace(
                    session_state={"waiting_reason": "Awaiting approval"}
                    if session_id == "session-wait"
                    else {}
                )
                for session_id in ids
            }

        def list_items(self, session_id: str, **_: object):
            data = []
            if session_id == "session-ok":
                data = [
                    SimpleNamespace(
                        type="function_call",
                        data=FunctionCallData(
                            agent="polly",
                            name="load_skill",
                            arguments='{"name":"cross-review"}',
                            call_id="call-1",
                        ),
                    )
                ]
            return SimpleNamespace(data=data, has_more=False, last_id=None)

    app = FastAPI()
    app.include_router(
        create_agent_activity_router(
            agent_store=SimpleNamespace(
                get=lambda agent_id: object() if agent_id == "agent-1" else None
            ),
            conversation_store=Conversations(),
            work_item_store=SimpleNamespace(list=lambda **_: [task]),
            work_item_run_store=SimpleNamespace(list_for_work_item=lambda *_args, **_kwargs: runs),
            project_store=SimpleNamespace(
                list=lambda **_: [
                    Project(id="project-1", name="Launch", owner_user_id=None, created_at=1)
                ]
            ),
        ),
        prefix="/v1",
    )

    response = TestClient(app).get("/v1/agent-bundles/agent-1/activity")

    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 3
    assert body["active_runs"] == 1
    assert body["waiting_runs"] == 1
    assert body["failed_runs"] == 1
    assert body["success_rate"] == 0.5
    assert body["recent_runs"][0]["id"] == "run-ok"
    assert body["recent_runs"][1]["waiting_reason"] == "Awaiting approval"
    assert body["recent_runs"][2]["failure_message"] == "Runner stopped"
    assert body["projects"] == [{"id": "project-1", "name": "Launch", "run_count": 3}]
    assert body["skills"] == [{"name": "cross-review", "uses": 1}]


def test_agent_activity_returns_404_for_unknown_agent() -> None:
    app = FastAPI()
    app.include_router(
        create_agent_activity_router(
            agent_store=SimpleNamespace(get=lambda _agent_id: None),
            conversation_store=SimpleNamespace(),
            work_item_store=SimpleNamespace(),
            work_item_run_store=SimpleNamespace(),
        ),
        prefix="/v1",
    )

    assert TestClient(app).get("/v1/agent-bundles/missing/activity").status_code == 404
