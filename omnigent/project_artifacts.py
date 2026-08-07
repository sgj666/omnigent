"""Project Artifact projections derived from TaskRun sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from omnigent.entities import FunctionCallData, FunctionCallOutputData, MessageData
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.file_store import FileStore
from omnigent.stores.work_item_run_store import WorkItemRunStore
from omnigent.stores.work_item_store import WorkItemStore

_PAGE_SIZE = 1000
_RESULT_SUMMARY_LIMIT = 4000


@dataclass(frozen=True)
class SessionRunResult:
    """Result fields persisted onto one product TaskRun."""

    summary: str | None
    artifact_refs: list[str]


def _assistant_text(data: MessageData) -> str | None:
    parts = [
        block["text"]
        for block in data.content
        if block.get("type") == "output_text" and isinstance(block.get("text"), str)
    ]
    text = "".join(parts).strip()
    return text[:_RESULT_SUMMARY_LIMIT] if text else None


def _output_file_id(output: str) -> str | None:
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    file_id = value.get("file_id") if isinstance(value, dict) else None
    return file_id if isinstance(file_id, str) and file_id else None


def collect_session_run_result(
    conversation_store: ConversationStore,
    file_store: FileStore,
    session_id: str,
) -> SessionRunResult:
    """Extract the final assistant summary and uploaded output files.

    Only successful ``upload_file`` function-call outputs count as artifacts.
    Session input attachments and unrelated file-list/download results are not
    promoted. Each referenced file is also checked against the session-scoped
    FileStore before it is accepted.
    """

    upload_calls: set[str] = set()
    artifact_refs: list[str] = []
    seen_file_ids: set[str] = set()
    summary: str | None = None
    after: str | None = None

    while True:
        page = conversation_store.list_items(
            session_id,
            limit=_PAGE_SIZE,
            after=after,
            order="asc",
        )
        for item in page.data:
            data = item.data
            if item.type == "function_call" and isinstance(data, FunctionCallData):
                if data.name == "upload_file":
                    upload_calls.add(data.call_id)
            elif item.type == "function_call_output" and isinstance(data, FunctionCallOutputData):
                if data.call_id not in upload_calls:
                    continue
                file_id = _output_file_id(data.output)
                if file_id is None or file_id in seen_file_ids:
                    continue
                if file_store.get(file_id, session_id=session_id) is None:
                    continue
                seen_file_ids.add(file_id)
                artifact_refs.append(f"file:{file_id}")
            elif (
                item.type == "message"
                and isinstance(data, MessageData)
                and data.role == "assistant"
            ):
                candidate = _assistant_text(data)
                if candidate is not None:
                    summary = candidate

        if not page.has_more or page.last_id is None:
            break
        after = page.last_id

    return SessionRunResult(summary=summary, artifact_refs=artifact_refs)


def list_project_artifacts(
    project_id: str,
    *,
    owner_user_id: str | None,
    work_item_store: WorkItemStore,
    work_item_run_store: WorkItemRunStore,
    file_store: FileStore,
) -> list[dict[str, Any]]:
    """Build a read-only Project Artifact view without copying file blobs."""

    rows: list[dict[str, Any]] = []
    tasks = [
        item
        for item in work_item_store.list(owner_user_id=owner_user_id)
        if item.project_id == project_id
    ]
    for task in tasks:
        runs = work_item_run_store.list_for_work_item(
            task.id,
            owner_user_id=owner_user_id,
        )
        for run in runs:
            for ref in run.artifact_refs:
                if not ref.startswith("file:"):
                    continue
                file_id = ref.removeprefix("file:")
                stored = (
                    file_store.get(file_id, session_id=run.session_id)
                    if run.session_id is not None
                    else None
                )
                available = stored is not None
                rows.append(
                    {
                        "id": file_id,
                        "object": "project.artifact",
                        "project_id": project_id,
                        "name": stored.filename if stored is not None else file_id,
                        "content_type": stored.content_type if stored is not None else None,
                        "bytes": stored.bytes if stored is not None else None,
                        "created_at": stored.created_at if stored is not None else None,
                        "version": 1,
                        "visibility": "private",
                        "available": available,
                        "summary": run.result_summary,
                        "work_item_id": task.id,
                        "work_item_title": task.title,
                        "work_item_run_id": run.id,
                        "session_id": run.session_id,
                        "download_url": (
                            f"/v1/sessions/{run.session_id}/resources/files/{file_id}/content"
                            if available and run.session_id is not None
                            else None
                        ),
                    }
                )

    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    for versions in by_name.values():
        versions.sort(
            key=lambda row: (
                row["created_at"] if row["created_at"] is not None else -1,
                row["id"],
                row["work_item_run_id"],
            )
        )
        for version, row in enumerate(versions, start=1):
            row["version"] = version

    rows.sort(
        key=lambda row: (
            row["created_at"] if row["created_at"] is not None else -1,
            row["id"],
            row["work_item_run_id"],
        ),
        reverse=True,
    )
    return rows
