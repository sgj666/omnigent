"""Project Artifact projection and API tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from omnigent.entities import (
    FunctionCallData,
    FunctionCallOutputData,
    MessageData,
    NewConversationItem,
)
from omnigent.project_artifacts import collect_session_run_result
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from omnigent.stores.work_item_run_store.sqlalchemy_store import SqlAlchemyWorkItemRunStore
from omnigent.stores.work_item_store.sqlalchemy_store import SqlAlchemyWorkItemStore

ALICE = "alice@example.com"
BOB = "bob@example.com"


def _as_user(user: str) -> dict[str, str]:
    return {"X-Forwarded-Email": user}


def test_collect_session_result_uses_only_upload_file_outputs(
    runtime_init: None,
    db_uri: str,
) -> None:
    """Input attachments and unrelated tool output are not Project Artifacts."""
    conversation_store = SqlAlchemyConversationStore(db_uri)
    file_store = SqlAlchemyFileStore(db_uri)
    session = conversation_store.create_conversation()
    input_file = file_store.create(
        "brief.txt",
        5,
        "text/plain",
        session_id=session.id,
    )
    output_file = file_store.create(
        "report.md",
        12,
        "text/markdown",
        session_id=session.id,
    )
    other_session = conversation_store.create_conversation()
    foreign_file = file_store.create(
        "foreign.txt",
        7,
        "text/plain",
        session_id=other_session.id,
    )

    conversation_store.append(
        session.id,
        [
            NewConversationItem(
                type="message",
                response_id="response_1",
                data=MessageData(
                    role="user",
                    content=[{"type": "input_file", "file_id": input_file.id}],
                ),
            ),
            NewConversationItem(
                type="function_call",
                response_id="response_1",
                data=FunctionCallData(
                    agent="polly",
                    name="list_files",
                    arguments="{}",
                    call_id="call_list",
                ),
            ),
            NewConversationItem(
                type="function_call_output",
                response_id="response_1",
                data=FunctionCallOutputData(
                    call_id="call_list",
                    output=json.dumps({"file_id": input_file.id}),
                ),
            ),
            NewConversationItem(
                type="function_call",
                response_id="response_1",
                data=FunctionCallData(
                    agent="polly",
                    name="upload_file",
                    arguments='{"path":"report.md"}',
                    call_id="call_upload",
                ),
            ),
            NewConversationItem(
                type="function_call_output",
                response_id="response_1",
                data=FunctionCallOutputData(
                    call_id="call_upload",
                    output=json.dumps(
                        {"file_id": output_file.id, "filename": output_file.filename}
                    ),
                ),
            ),
            NewConversationItem(
                type="function_call",
                response_id="response_1",
                data=FunctionCallData(
                    agent="polly",
                    name="upload_file",
                    arguments='{"path":"foreign.txt"}',
                    call_id="call_foreign",
                ),
            ),
            NewConversationItem(
                type="function_call_output",
                response_id="response_1",
                data=FunctionCallOutputData(
                    call_id="call_foreign",
                    output=json.dumps({"file_id": foreign_file.id}),
                ),
            ),
            NewConversationItem(
                type="message",
                response_id="response_1",
                data=MessageData(
                    role="assistant",
                    agent="polly",
                    content=[
                        {"type": "output_text", "text": "Created the final report.\n"},
                        {"type": "output_text", "text": "It is ready for review."},
                    ],
                ),
            ),
        ],
    )

    result = collect_session_run_result(conversation_store, file_store, session.id)

    assert result.summary == "Created the final report.\nIt is ready for review."
    assert result.artifact_refs == [f"file:{output_file.id}"]


@pytest.fixture()
def artifact_app(
    runtime_init: None,
    db_uri: str,
    tmp_path: Path,
) -> FastAPI:
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    return create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        permission_store=SqlAlchemyPermissionStore(db_uri),
        project_store=SqlAlchemyProjectStore(db_uri),
        work_item_store=SqlAlchemyWorkItemStore(db_uri),
        work_item_run_store=SqlAlchemyWorkItemRunStore(db_uri),
        auth_provider=UnifiedAuthProvider(source="header"),
    )


@pytest_asyncio.fixture()
async def artifact_client(artifact_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=artifact_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_project_artifacts_are_versioned_traced_and_owner_private(
    artifact_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifacts expose real file metadata and TaskRun back-links only to the owner."""
    project = (
        await artifact_client.post(
            "/v1/projects",
            json={"name": "Release"},
            headers=_as_user(ALICE),
        )
    ).json()
    work_item_store = SqlAlchemyWorkItemStore(db_uri)
    run_store = SqlAlchemyWorkItemRunStore(db_uri)
    conversation_store = SqlAlchemyConversationStore(db_uri)
    file_store = SqlAlchemyFileStore(db_uri)
    task = work_item_store.create(
        "1" * 32,
        owner_user_id=ALICE,
        title="Publish release notes",
        description=None,
        state="in_progress",
        priority="high",
        project_id=project["id"],
        assignee_agent_id="2" * 32,
        due_at=None,
    )
    monkeypatch.setattr(
        "omnigent.stores.file_store.sqlalchemy_store.now_epoch",
        iter([100, 200]).__next__,
    )

    created_files = []
    for index, summary in enumerate(("First draft", "Final revision"), start=1):
        session = conversation_store.create_conversation(project_id=project["id"])
        run = run_store.create(
            str(index + 2) * 32,
            work_item_id=task.id,
            owner_user_id=ALICE,
            agent_id="2" * 32,
            runtime_id="host-local",
            workspace="/work/release",
            trigger="manual",
            retry_of_run_id=None,
        )
        run_store.bind_session(run.id, owner_user_id=ALICE, session_id=session.id)
        stored = file_store.create(
            "release-notes.md",
            100 * index,
            "text/markdown",
            session_id=session.id,
        )
        created_files.append(stored)
        run_store.record_result_for_session(
            session.id,
            result_summary=summary,
            artifact_refs=[f"file:{stored.id}"],
        )

    response = await artifact_client.get(
        f"/v1/projects/{project['id']}/artifacts",
        headers=_as_user(ALICE),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [row["version"] for row in body["data"]] == [2, 1]
    assert [row["id"] for row in body["data"]] == [
        created_files[1].id,
        created_files[0].id,
    ]
    newest = body["data"][0]
    assert newest == {
        "id": created_files[1].id,
        "object": "project.artifact",
        "project_id": project["id"],
        "name": "release-notes.md",
        "content_type": "text/markdown",
        "bytes": 200,
        "created_at": 200,
        "version": 2,
        "visibility": "private",
        "available": True,
        "summary": "Final revision",
        "work_item_id": task.id,
        "work_item_title": task.title,
        "work_item_run_id": "4" * 32,
        "session_id": newest["session_id"],
        "download_url": (
            f"/v1/sessions/{newest['session_id']}/resources/files/{created_files[1].id}/content"
        ),
    }

    project_list = (await artifact_client.get("/v1/projects", headers=_as_user(ALICE))).json()[
        "data"
    ]
    assert project_list == [
        {
            **project,
            "session_count": 2,
            "artifact_count": 2,
            "latest_artifact_name": "release-notes.md",
            "latest_artifact_at": 200,
        }
    ]

    forbidden = await artifact_client.get(
        f"/v1/projects/{project['id']}/artifacts",
        headers=_as_user(BOB),
    )
    assert forbidden.status_code == 404


async def test_terminal_session_automatically_projects_task_run_result(
    artifact_client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """The real Session terminal hook records summary and artifact references."""
    from omnigent.server import session_live_state

    project = (
        await artifact_client.post(
            "/v1/projects",
            json={"name": "Automatic projection"},
            headers=_as_user(ALICE),
        )
    ).json()
    work_item_store = SqlAlchemyWorkItemStore(db_uri)
    run_store = SqlAlchemyWorkItemRunStore(db_uri)
    conversation_store = SqlAlchemyConversationStore(db_uri)
    file_store = SqlAlchemyFileStore(db_uri)
    task = work_item_store.create(
        "a" * 32,
        owner_user_id=ALICE,
        title="Generate report",
        description=None,
        state="in_progress",
        priority="medium",
        project_id=project["id"],
        assignee_agent_id="b" * 32,
        due_at=None,
    )
    session = conversation_store.create_conversation(project_id=project["id"])
    run = run_store.create(
        "c" * 32,
        work_item_id=task.id,
        owner_user_id=ALICE,
        agent_id="b" * 32,
        runtime_id="host-local",
        workspace="/work/report",
        trigger="manual",
        retry_of_run_id=None,
    )
    run_store.bind_session(run.id, owner_user_id=ALICE, session_id=session.id)
    run_store.transition(run.id, state="running")
    output = file_store.create(
        "report.csv",
        42,
        "text/csv",
        session_id=session.id,
    )
    conversation_store.append(
        session.id,
        [
            NewConversationItem(
                type="function_call",
                response_id="response_done",
                data=FunctionCallData(
                    agent="polly",
                    name="upload_file",
                    arguments='{"path":"report.csv"}',
                    call_id="call_report",
                ),
            ),
            NewConversationItem(
                type="function_call_output",
                response_id="response_done",
                data=FunctionCallOutputData(
                    call_id="call_report",
                    output=json.dumps({"file_id": output.id, "filename": output.filename}),
                ),
            ),
            NewConversationItem(
                type="message",
                response_id="response_done",
                data=MessageData(
                    role="assistant",
                    agent="polly",
                    content=[{"type": "output_text", "text": "Report generated."}],
                ),
            ),
        ],
    )

    session_live_state.persist_work_item_run_status(
        session.id,
        "idle",
        response_id="response_done",
    )

    projected = None
    for _ in range(100):
        projected = run_store.get(run.id, owner_user_id=ALICE)
        if projected is not None and projected.artifact_refs:
            break
        await asyncio.sleep(0.01)

    assert projected is not None
    assert projected.state.value == "succeeded"
    assert projected.result_summary == "Report generated."
    assert projected.artifact_refs == [f"file:{output.id}"]
