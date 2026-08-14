"""
Integration tests for git worktree creation on the dedicated per-session
bind endpoint ``POST /v1/hosts/{host_id}/runners`` (``launch_runner``).

This is the endpoint the fork-resume flow uses to bind an already-existing
(unbound) session to a host + directory. Unlike ``POST /v1/sessions`` —
which creates the worktree before the conversation row exists —
``launch_runner`` operates on a row that already exists, so it must create
the worktree at bind time and roll it back if the bind/launch fails.

Drives the endpoint through the full app and a fake host that auto-replies
to the host control frames (``host.stat`` for workspace validation,
``host.create_worktree``, ``host.launch_runner``, and
``host.remove_worktree`` for rollback). See designs/SESSION_GIT_WORKTREE.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException

from omnigent.entities import AgentBundleSnapshot
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.host.frames import (
    HostCreateWorktreeFrame,
    HostHelloFrame,
    HostLaunchRunnerFrame,
    HostRemoveWorktreeFrame,
    HostStatFrame,
    HostStopRunnerFrame,
    decode_host_frame,
)
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import LEVEL_OWNER, RESERVED_USER_LOCAL
from omnigent.server.host_registry import HostConnection
from omnigent.server.routes import _host_worktree
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.comment_store.sqlalchemy_store import SqlAlchemyCommentStore
from omnigent.stores.conversation_store.sqlalchemy_store import (
    SqlAlchemyConversationStore,
)
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.run_store.sqlalchemy_store import SqlAlchemyRunStore
from tests.server.helpers import create_test_agent

pytestmark = pytest.mark.asyncio

_HOST_ID = "51dc949aba31e24ca8f047d6fba31a0d"
_SOURCE_REPO = "/Users/alice/myrepo"


@pytest.fixture()
def app(runtime_init: None, db_uri: str, tmp_path: Path) -> FastAPI:
    """FastAPI app wired WITH ``host_store`` so ``launch_runner`` can
    resolve host ownership and launch a runner.

    Overrides the shared ``app`` fixture (which passes
    ``host_store=None`` and so can't run the dedicated launch endpoint).
    The shared ``client`` fixture depends on this ``app``.

    :param runtime_init: Initializes the runtime + mock LLM.
    :param db_uri: SQLite database URI.
    :param tmp_path: Pytest temp dir for artifacts and cache.
    :returns: A configured FastAPI app with host routes mounted.
    """
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    return create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifact_store,
        agent_cache=AgentCache(
            artifact_store=artifact_store,
            cache_dir=tmp_path / "cache",
        ),
        comment_store=SqlAlchemyCommentStore(db_uri),
        host_store=HostStore(db_uri),
    )


class _FakeWebSocket:
    """Minimal WebSocket stand-in (the registry only enqueues)."""

    async def send_text(self, data: str) -> None:
        """No-op send — frames flow through the outbound queue.

        :param data: JSON-encoded frame text (ignored).
        """


@dataclass
class _HostCapture:
    """
    Frames a fake host received during one ``launch_runner`` call.

    :param create: ``host.create_worktree`` frames received.
    :param launch: ``host.launch_runner`` frames received.
    :param remove: ``host.remove_worktree`` frames received (a non-empty
        list proves the rollback path fired).
    """

    create: list[HostCreateWorktreeFrame] = field(default_factory=list)
    launch: list[HostLaunchRunnerFrame] = field(default_factory=list)
    remove: list[HostRemoveWorktreeFrame] = field(default_factory=list)
    stop: list[HostStopRunnerFrame] = field(default_factory=list)


# register(*, create_status=, create_error=, launch_status=) -> _HostCapture
RegisterHost = Callable[..., _HostCapture]


@pytest_asyncio.fixture()
async def register_host(
    app: FastAPI,
    db_uri: str,
) -> AsyncIterator[RegisterHost]:
    """Yield a factory that registers a fake host with a replying drain.

    The drain answers ``host.stat`` (workspace validation passes),
    ``host.create_worktree``, ``host.launch_runner``, and
    ``host.remove_worktree`` — capturing each into a :class:`_HostCapture`.
    Every drain is poisoned and awaited at teardown so no background task
    leaks into the next test's event loop.

    :param app: App whose ``host_registry`` to register into.
    :param db_uri: DB URI so the ``host_id`` FK target row exists.
    :returns: Async iterator yielding a ``register`` factory. Kwargs:
        ``create_status`` (``"ok"``/``"failed"``), ``create_error``
        (host failure detail), ``launch_status``
        (``"launched"``/``"failed"``). Returns the :class:`_HostCapture`
        accumulating frames the host received.
    """
    conns: list[HostConnection] = []

    def _register(
        *,
        create_status: str = "ok",
        create_error: str | None = None,
        launch_status: str = "launched",
        stop_status: str | tuple[str, ...] = "ok",
    ) -> _HostCapture:
        HostStore(db_uri).upsert_on_connect(_HOST_ID, "wt-host", RESERVED_USER_LOCAL)
        conn = app.state.host_registry.register(
            host_id=_HOST_ID,
            ws=_FakeWebSocket(),  # type: ignore[arg-type] — duck-typed
            hello=HostHelloFrame(version="0.1.0-test", frame_protocol_version=1, name="wt-host"),
            owner=RESERVED_USER_LOCAL,
        )
        cap = _HostCapture()
        stop_statuses = (stop_status,) if isinstance(stop_status, str) else stop_status
        stop_index = 0

        async def _drain() -> None:
            """Answer stat/create/launch/remove frames; capture them."""
            nonlocal stop_index
            while True:
                frame_text = await conn.outbound_queue.get()
                if frame_text is None:
                    return
                frame = decode_host_frame(frame_text)
                if isinstance(frame, HostStatFrame):
                    fut = conn.pending_stats.pop(frame.request_id, None)
                    if fut is not None and not fut.done():
                        fut.set_result(
                            {
                                "status": "ok",
                                "exists": True,
                                "type": "directory",
                                "canonical_path": frame.path,
                                "error": None,
                            }
                        )
                elif isinstance(frame, HostCreateWorktreeFrame):
                    cap.create.append(frame)
                    fut = conn.pending_create_worktrees.pop(frame.request_id, None)
                    if fut is not None and not fut.done():
                        if create_status == "ok":
                            dirname = frame.branch_name.replace("/", "-")
                            fut.set_result(
                                {
                                    "status": "ok",
                                    "worktree_path": frame.target_path
                                    or f"{frame.repo_path}-worktrees/{dirname}",
                                    "branch": frame.branch_name,
                                    "error": None,
                                }
                            )
                        else:
                            fut.set_result(
                                {
                                    "status": "failed",
                                    "worktree_path": None,
                                    "branch": None,
                                    "error": create_error,
                                }
                            )
                elif isinstance(frame, HostLaunchRunnerFrame):
                    cap.launch.append(frame)
                    fut = conn.pending_launches.pop(frame.request_id, None)
                    if fut is not None and not fut.done():
                        fut.set_result(
                            {
                                "status": launch_status,
                                "runner_id": (
                                    "runner_from_host" if launch_status == "launched" else None
                                ),
                                "error": None if launch_status == "launched" else "boom",
                            }
                        )
                elif isinstance(frame, HostRemoveWorktreeFrame):
                    cap.remove.append(frame)
                    fut = conn.pending_remove_worktrees.pop(frame.request_id, None)
                    if fut is not None and not fut.done():
                        fut.set_result({"status": "ok", "error": None})
                elif isinstance(frame, HostStopRunnerFrame):
                    cap.stop.append(frame)
                    fut = conn.pending_stops.pop(frame.request_id, None)
                    if fut is not None and not fut.done():
                        current_stop_status = stop_statuses[
                            min(stop_index, len(stop_statuses) - 1)
                        ]
                        stop_index += 1
                        fut.set_result(
                            {
                                "status": current_stop_status,
                                "error": (None if current_stop_status == "ok" else "stop boom"),
                            }
                        )

        conn._drain_task_for_test = asyncio.create_task(_drain())  # type: ignore[attr-defined]
        conns.append(conn)
        return cap

    yield _register

    for conn in conns:
        conn.outbound_queue.put_nowait(None)
        task = conn._drain_task_for_test  # type: ignore[attr-defined]
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        if not task.done():
            task.cancel()


@pytest.mark.parametrize(
    "followup_outcome",
    ["launched", "launch_failed", "stop_failed", "launch_stop_failed"],
)
async def test_run_child_reserves_attempt_and_launches_in_two_repo_workspace(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    app: FastAPI,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    followup_outcome: str,
) -> None:
    """The real dispatch tool reserves and accepts one canonical Task/Attempt."""
    from omnigent.runner import app as runner_app
    from omnigent.runner.tool_dispatch import execute_tool
    from omnigent.server.routes import sessions as sessions_mod

    cap = register_host()
    agent_payload = await create_test_agent(
        client,
        name="run-coordinator",
        sub_agents=[{"name": "worker"}],
    )
    agent = SqlAlchemyAgentStore(db_uri).get(agent_payload["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    workspace_root = "/Users/alice/project"
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path=workspace_root,
        repositories=(("api", "api"), ("web", "web")),
    )
    root = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace_root,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run = run_store.create_run_idempotent(
        auth_scope="user:local",
        actor_id=RESERVED_USER_LOCAL,
        source="api:test",
        source_event_id="real-two-repo-child",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    ).run

    runner_http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        base_url="http://runner",
    )

    async def _runner_client(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
        return runner_http

    dispatch_ids = iter(("a" * 32, "b" * 32, "c" * 32, "d" * 32))
    fail_dispatch_once = False
    dispatch_calls: list[str | None] = []

    async def _dispatch(*args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal fail_dispatch_once
        event = args[2]
        dispatch_calls.append(getattr(event, "dispatch_source_id", None))
        if fail_dispatch_once:
            fail_dispatch_once = False
            raise OmnigentError("dispatch failed once", code=ErrorCode.RUNNER_UNAVAILABLE)
        return SimpleNamespace(
            item_id=next(dispatch_ids),
            pending_id=None,
            terminal_error=None,
        )

    async def _relay_ready(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runner_app, "get_session_agent_id", lambda _sid: agent.id)
    monkeypatch.setattr(runner_app, "register_child_session", lambda *a, **k: None)
    monkeypatch.setattr(sessions_mod, "_get_runner_client", _runner_client)
    monkeypatch.setattr(sessions_mod, "_dispatch_session_event_to_runner", _dispatch)
    monkeypatch.setattr(sessions_mod, "_ensure_runner_relay_ready", _relay_ready)
    session_inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    requests: list[str] = []

    class _RecordingClient:
        async def get(self, url: str, **kwargs: object) -> httpx.Response:
            requests.append(f"GET {url}")
            return await client.get(url, **kwargs)

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            requests.append(f"POST {url}")
            return await client.post(url, **kwargs)

        async def delete(self, url: str, **kwargs: object) -> httpx.Response:
            requests.append(f"DELETE {url}")
            return await client.delete(url, **kwargs)

    try:
        try:
            output = await asyncio.wait_for(
                execute_tool(
                    tool_name="sys_session_send",
                    arguments=json.dumps(
                        {
                            "agent": "worker",
                            "title": "implement both repos",
                            "args": "implement both repos",
                        }
                    ),
                    server_client=_RecordingClient(),  # type: ignore[arg-type]
                    conversation_id=root.id,
                    agent_spec=SimpleNamespace(sub_agents=[SimpleNamespace(name="worker")]),
                    session_inbox=session_inbox,
                ),
                timeout=10.0,
            )
        except TimeoutError:
            pytest.fail(f"tool dispatch timed out after requests: {requests}")
    finally:
        runner_app.unregister_subagent_work(
            next(
                (
                    work.child_session_id
                    for work in runner_app.list_subagent_work(root.id)
                    if work.title == "implement both repos"
                ),
                "missing",
            )
        )
        runner_app._session_inboxes_ref.pop(root.id, None)

    tool_result = json.loads(output)
    assert tool_result["status"] == "launching", tool_result
    child_id = tool_result["conversation_id"]
    child = (await client.get(f"/v1/sessions/{child_id}")).json()
    tasks = run_store.list_tasks(run.id)
    attempts = run_store.list_attempts(run.id)
    assert len(tasks) == 1
    assert tasks[0].title == "implement both repos"
    assert len(attempts) == 1
    assert attempts[0].child_session_id == child_id
    assert attempts[0].status.value == "running"
    leases = run_store.list_active_worktree_leases(run.id)
    assert len(leases) == 2
    attempt_root = Path(child["workspace"])
    assert {lease.worktree_path for lease in leases} == {
        str(attempt_root / "api"),
        str(attempt_root / "web"),
    }
    assert {frame.target_path for frame in cap.create} == {
        str(attempt_root / "api"),
        str(attempt_root / "web"),
    }
    assert cap.launch[-1].workspace == str(attempt_root)

    relay_failure_once = True

    async def _forward_terminal(*_args: object, **_kwargs: object) -> SimpleNamespace:
        nonlocal relay_failure_once
        if relay_failure_once:
            relay_failure_once = False
            raise OmnigentError(
                "original parent relay failure",
                code=ErrorCode.RUNNER_UNAVAILABLE,
            )
        return SimpleNamespace(status_code=200, body="")

    monkeypatch.setattr(
        sessions_mod,
        "_forward_session_change_to_runner",
        _forward_terminal,
    )
    relay_failure = await client.post(
        f"/v1/sessions/{child_id}/events",
        json={"type": "external_session_status", "data": {"status": "idle"}},
    )
    assert relay_failure.status_code == 503, relay_failure.text
    assert "original parent relay failure" in relay_failure.text
    assert cap.remove == []
    retained_terminal_leases = run_store.list_active_worktree_leases(run.id)
    assert len(retained_terminal_leases) == 2
    assert {lease.status.value for lease in retained_terminal_leases} == {"recovery_required"}
    removed_at_terminal = len(cap.remove)

    followup_cap = register_host(
        launch_status=(
            "failed" if followup_outcome in {"launch_failed", "launch_stop_failed"} else "launched"
        ),
        stop_status=(
            ("ok", "failed")
            if followup_outcome == "launch_stop_failed"
            else "failed"
            if followup_outcome == "stop_failed"
            else "ok"
        ),
    )

    followup_inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    followup = await execute_tool(
        tool_name="sys_session_send",
        arguments=json.dumps(
            {
                "agent": "worker",
                "title": "implement both repos",
                "args": "continue in a fresh attempt",
            }
        ),
        server_client=_RecordingClient(),  # type: ignore[arg-type]
        conversation_id=root.id,
        agent_spec=SimpleNamespace(sub_agents=[SimpleNamespace(name="worker")]),
        session_inbox=followup_inbox,
    )
    runner_app.unregister_subagent_work(child_id)
    runner_app._session_inboxes_ref.pop(root.id, None)

    followup_tasks = run_store.list_tasks(run.id)
    followup_attempts = run_store.list_attempts(run.id)
    assert len(followup_tasks) == 1
    assert len(followup_attempts) == 2
    assert followup_attempts[0].task_id == followup_attempts[1].task_id
    assert followup_attempts[0].id != followup_attempts[1].id
    if followup_outcome != "launched":
        assert followup.startswith("Error: failed to send message to child")
        assert followup_attempts[1].status.value == "failed"
        assert len(followup_cap.create) == 2
        failed_child = (await client.get(f"/v1/sessions/{child_id}")).json()
        if followup_outcome in {"stop_failed", "launch_stop_failed"}:
            retained = run_store.list_active_worktree_leases(run.id)
            assert len(retained) == 4
            assert {lease.status.value for lease in retained} == {"recovery_required"}
            assert followup_cap.remove == []
            if followup_outcome == "stop_failed":
                assert failed_child["workspace"] == str(attempt_root)
                assert failed_child["runner_id"] == child["runner_id"]
                assert followup_cap.launch == []
            else:
                assert failed_child["workspace"] != str(attempt_root)
                assert failed_child["runner_id"] is not None
                assert failed_child["runner_id"] != child["runner_id"]
                assert len(followup_cap.launch) == 1
                assert len(followup_cap.stop) == 2

                from omnigent.server.routes._sessions import helpers

                queried_runner_ids: list[str] = []

                async def _runner_alive(
                    _host_conn: object,
                    _host_registry: object,
                    runner_id: str,
                ) -> str:
                    queried_runner_ids.append(runner_id)
                    return "alive"

                monkeypatch.setattr(helpers, "_query_host_runner_status", _runner_alive)
                stop = asyncio.Event()
                maintenance = asyncio.create_task(
                    _host_worktree.maintain_attempt_worktree_leases(
                        app.state.host_registry,
                        stop,
                        conversation_store=SqlAlchemyConversationStore(db_uri),
                        interval_s=0.01,
                    )
                )
                try:
                    async with asyncio.timeout(2):
                        while len(followup_cap.stop) < 3:
                            await asyncio.sleep(0.01)
                finally:
                    stop.set()
                    await maintenance
                assert queried_runner_ids[-1] == failed_child["runner_id"]
                assert followup_cap.remove == []
                still_retained = (await client.get(f"/v1/sessions/{child_id}")).json()
                assert still_retained["runner_id"] == failed_child["runner_id"]

                async def _runner_dead(*_args: object, **_kwargs: object) -> str:
                    return "dead"

                monkeypatch.setattr(helpers, "_query_host_runner_status", _runner_dead)
                stop = asyncio.Event()
                maintenance = asyncio.create_task(
                    _host_worktree.maintain_attempt_worktree_leases(
                        app.state.host_registry,
                        stop,
                        conversation_store=SqlAlchemyConversationStore(db_uri),
                        interval_s=0.01,
                    )
                )
                try:
                    async with asyncio.timeout(2):
                        while followup_cap.remove == []:
                            await asyncio.sleep(0.01)
                finally:
                    stop.set()
                    await maintenance
                recovered_child = (await client.get(f"/v1/sessions/{child_id}")).json()
                assert recovered_child["runner_id"] is None
                retained_after_recovery = run_store.list_active_worktree_leases(run.id)
                assert len(retained_after_recovery) == 2
                assert {lease.status.value for lease in retained_after_recovery} == {
                    "recovery_required"
                }
        else:
            assert failed_child["workspace"] == str(attempt_root)
            retained = run_store.list_active_worktree_leases(run.id)
            assert len(retained) == 2
            assert {lease.status.value for lease in retained} == {"recovery_required"}
            assert len(followup_cap.remove) == 2
            assert failed_child["runner_id"] is None
            assert len(followup_cap.launch) == 1
        deleted = await client.delete(f"/v1/sessions/{child_id}")
        assert deleted.status_code == 200, deleted.text
        await runner_http.aclose()
        return

    assert json.loads(followup)["conversation_id"] == child_id
    followup_leases = run_store.list_active_worktree_leases(run.id)
    assert len(followup_leases) == 2
    followup_root = Path((await client.get(f"/v1/sessions/{child_id}")).json()["workspace"])
    assert followup_root != attempt_root
    assert {lease.worktree_path for lease in followup_leases} == {
        str(followup_root / "api"),
        str(followup_root / "web"),
    }
    assert len(followup_cap.launch) == 1
    assert followup_cap.launch[-1].workspace == str(followup_root)
    assert len(cap.remove) == removed_at_terminal

    second_terminal = await client.post(
        f"/v1/sessions/{child_id}/events",
        json={"type": "external_session_status", "data": {"status": "idle"}},
    )
    assert second_terminal.status_code == 202, second_terminal.text
    retained_second_attempt = run_store.list_active_worktree_leases(run.id)
    assert len(retained_second_attempt) == 2
    assert {lease.status.value for lease in retained_second_attempt} == {"recovery_required"}
    assert len(followup_cap.remove) == 2

    retry_payload = {
        "type": "message",
        "data": {
            "role": "user",
            "content": [{"type": "input_text", "text": "resume prepared dispatch"}],
        },
        "dispatch_source_id": "retry-after-dispatch-failure",
    }
    fail_dispatch_once = True
    failed_dispatch = await client.post(
        f"/v1/sessions/{child_id}/events",
        json=retry_payload,
    )
    assert failed_dispatch.status_code == 503, failed_dispatch.text
    prepared_attempts = run_store.list_attempts(run.id)
    assert len(prepared_attempts) == 3
    assert prepared_attempts[-1].status.value == "queued"
    assert prepared_attempts[-1].dispatch_call_id is None
    assert len(run_store.list_active_worktree_leases(run.id)) == 2
    create_count = len(followup_cap.create)
    launch_count = len(followup_cap.launch)

    resumed = await client.post(f"/v1/sessions/{child_id}/events", json=retry_payload)
    assert resumed.status_code == 202, resumed.text
    assert resumed.json().get("replayed") is not True
    assert dispatch_calls[-2:] == [
        "retry-after-dispatch-failure",
        "retry-after-dispatch-failure",
    ]
    assert len(run_store.list_attempts(run.id)) == 3
    assert len(followup_cap.create) == create_count
    assert len(followup_cap.launch) == launch_count

    accepted_replay = await client.post(
        f"/v1/sessions/{child_id}/events",
        json=retry_payload,
    )
    assert accepted_replay.status_code == 202, accepted_replay.text
    assert accepted_replay.json()["replayed"] is True
    assert len(dispatch_calls) == 4

    async def _stop_via_runner(*_args: object, **_kwargs: object) -> bool:
        return True

    monkeypatch.setattr(sessions_mod, "_stop_session_via_runner", _stop_via_runner)
    prepared_terminal = await client.post(
        f"/v1/sessions/{child_id}/events",
        json={"type": "stop_session", "data": {}},
    )
    assert prepared_terminal.status_code == 202, prepared_terminal.text
    assert run_store.list_active_worktree_leases(run.id) == ()
    assert len(followup_cap.remove) == 6

    concurrent_payloads = (
        {
            "type": "message",
            "data": {
                "role": "user",
                "content": [{"type": "input_text", "text": "concurrent a"}],
            },
            "dispatch_source_id": "concurrent-a",
        },
        {
            "type": "message",
            "data": {
                "role": "user",
                "content": [{"type": "input_text", "text": "concurrent b"}],
            },
            "dispatch_source_id": "concurrent-b",
        },
    )
    concurrent = await asyncio.gather(
        *(
            client.post(f"/v1/sessions/{child_id}/events", json=body)
            for body in concurrent_payloads
        )
    )
    assert sorted(response.status_code for response in concurrent) == [202, 409]
    assert len(run_store.list_tasks(run.id)) == 1
    assert len(run_store.list_attempts(run.id)) == 4
    assert len(run_store.list_active_worktree_leases(run.id)) == 2
    assert len(followup_cap.launch) == 3
    winning_index = next(i for i, response in enumerate(concurrent) if response.status_code == 202)

    replay = await client.post(
        f"/v1/sessions/{child_id}/events",
        json=concurrent_payloads[winning_index],
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["replayed"] is True
    assert len(run_store.list_attempts(run.id)) == 4
    assert len(followup_cap.launch) == 3

    third_terminal = await client.post(
        f"/v1/sessions/{child_id}/events",
        json={"type": "external_session_status", "data": {"status": "idle"}},
    )
    assert third_terminal.status_code == 202, third_terminal.text
    retained_third_attempt = run_store.list_active_worktree_leases(run.id)
    assert len(retained_third_attempt) == 2
    assert {lease.status.value for lease in retained_third_attempt} == {"recovery_required"}
    assert len(followup_cap.remove) == 6

    deleted = await client.delete(f"/v1/sessions/{child_id}")

    assert deleted.status_code == 200, deleted.text
    assert len(followup_cap.remove) == 8
    assert run_store.list_active_worktree_leases(run.id) == ()
    await runner_http.aclose()


async def test_run_control_plane_child_uses_shared_workspace_without_worktree(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """A control-plane worker keeps its Attempt but writes the shared workspace."""
    cap = register_host()
    agent_payload = await create_test_agent(
        client,
        name="run-coordinator-shared",
        sub_agents=[
            {
                "name": "requirement-analyst",
                "executor_config": {"run_workspace": "shared"},
            }
        ],
    )
    agent = SqlAlchemyAgentStore(db_uri).get(agent_payload["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    workspace_root = "/Users/alice/project"
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path=workspace_root,
        repositories=(("product", "product"),),
    )
    root = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace_root,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run = run_store.create_run_idempotent(
        auth_scope="user:local",
        actor_id=RESERVED_USER_LOCAL,
        source="api:test",
        source_event_id="shared-control-plane-child",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    ).run

    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent.id,
            "parent_session_id": root.id,
            "sub_agent_name": "requirement-analyst",
            "title": "requirement-analyst:review",
            "dispatch_source_id": "sys_session_send:shared-control-plane-child",
        },
    )

    assert response.status_code == 201, response.text
    child = response.json()
    assert child["workspace"] == workspace_root
    attempts = run_store.list_attempts(run.id)
    assert len(attempts) == 1
    assert attempts[0].child_session_id == child["id"]
    assert attempts[0].status.value == "queued"
    assert run_store.list_active_worktree_leases(run.id) == ()
    assert cap.create == []


async def test_run_child_worktree_uses_requested_fixed_base_ref(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """A fixed candidate is passed to host worktree creation, not dropped."""
    cap = register_host()
    agent_payload = await create_test_agent(
        client,
        name="run-fixed-candidate",
        sub_agents=[{"name": "verifier"}],
    )
    agent = SqlAlchemyAgentStore(db_uri).get(agent_payload["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    workspace_root = "/Users/alice/project"
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path=workspace_root,
        repositories=(("product", "product"),),
    )
    root = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace_root,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run_store.create_run_idempotent(
        auth_scope="user:local",
        actor_id=RESERVED_USER_LOCAL,
        source="api:test",
        source_event_id="fixed-candidate-child",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    )

    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent.id,
            "parent_session_id": root.id,
            "sub_agent_name": "verifier",
            "title": "verifier:fixed-candidate",
            "dispatch_source_id": "sys_session_send:fixed-candidate-child",
            "worktree_base_ref": "refs/candidates/final",
            "run_child_sandbox_override": "none",
        },
    )

    assert response.status_code == 201, response.text
    assert len(cap.create) == 1
    assert cap.create[0].base_branch == "refs/candidates/final"
    child_row = SqlAlchemyConversationStore(db_uri).get_conversation(response.json()["id"])
    assert child_row is not None
    assert child_row.labels["omnigent.run_child.sandbox_override"] == "none"


async def test_native_run_child_terminal_failure_tears_down_and_allows_new_attempt(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    app: FastAPI,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.server.routes import sessions as sessions_mod
    from tests.server.integration.test_sessions_child_sessions import (
        _bundle_with_harnessed_subagents,
    )

    cap = register_host()
    bundle = _bundle_with_harnessed_subagents(
        "native-run-coordinator",
        [{"name": "worker", "harness": "claude-native"}],
    )
    created_agent = await client.post(
        "/v1/sessions",
        data={"metadata": json.dumps({})},
        files={"bundle": ("agent.tar.gz", bundle, "application/gzip")},
    )
    assert created_agent.status_code == 201, created_agent.text
    agent_response = await client.get(f"/v1/sessions/{created_agent.json()['session_id']}/agent")
    assert agent_response.status_code == 200, agent_response.text
    agent = SqlAlchemyAgentStore(db_uri).get(agent_response.json()["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path="/Users/alice/native-run",
        repositories=(("api", "api"), ("web", "web")),
    )
    root = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace.root_path,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run = run_store.create_run_idempotent(
        auth_scope="user:local",
        actor_id=RESERVED_USER_LOCAL,
        source="api:test",
        source_event_id="native-terminal-failure",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    ).run
    child_response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent.id,
            "parent_session_id": root.id,
            "sub_agent_name": "worker",
            "title": "native worker",
            "dispatch_source_id": "create-native-worker",
        },
    )
    assert child_response.status_code == 201, child_response.text
    child_id = child_response.json()["id"]
    forwarded_statuses: list[dict[str, object]] = []

    def _runner_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith("/resources/terminals"):
            return httpx.Response(
                503,
                json={
                    "error": {
                        "code": "native_terminal_start_failed",
                        "message": "claude CLI unavailable",
                    }
                },
            )
        if body.get("type") == "external_session_status":
            forwarded_statuses.append(body)
        return httpx.Response(200, json={})

    runner_http = httpx.AsyncClient(
        transport=httpx.MockTransport(_runner_handler),
        base_url="http://runner",
    )

    async def _runner_client(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
        return runner_http

    async def _relay_ready(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(sessions_mod, "_get_runner_client", _runner_client)
    monkeypatch.setattr(sessions_mod, "_ensure_runner_relay_ready", _relay_ready)
    try:
        first_failure = await client.post(
            f"/v1/sessions/{child_id}/events",
            json={
                "type": "message",
                "data": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "first attempt"}],
                },
                "dispatch_source_id": "native-failure-1",
            },
        )
        assert first_failure.status_code == 202, first_failure.text
        assert first_failure.json()["terminal"] == "failed"
        assert first_failure.json().get("replayed") is not True
        tasks = run_store.list_tasks(run.id)
        attempts = run_store.list_attempts(run.id)
        assert len(tasks) == 1
        assert tasks[0].status.value == "failed"
        assert len(attempts) == 1
        assert attempts[0].status.value == "failed"
        assert run_store.get_run(run.id).status.value == "failed"
        retained_first_attempt = run_store.list_active_worktree_leases(run.id)
        assert len(retained_first_attempt) == 2
        assert {lease.status.value for lease in retained_first_attempt} == {"recovery_required"}
        assert cap.remove == []
        assert forwarded_statuses == [
            {
                "type": "external_session_status",
                "data": {"status": "failed", "output": "claude CLI unavailable"},
            }
        ]

        second_failure = await client.post(
            f"/v1/sessions/{child_id}/events",
            json={
                "type": "message",
                "data": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "fresh attempt"}],
                },
                "dispatch_source_id": "native-failure-2",
            },
        )
        assert second_failure.status_code == 202, second_failure.text
        attempts = run_store.list_attempts(run.id)
        assert len(attempts) == 2
        assert attempts[0].id != attempts[1].id
        assert attempts[1].status.value == "failed"
        retained_second_attempt = run_store.list_active_worktree_leases(run.id)
        assert len(retained_second_attempt) == 2
        assert {lease.status.value for lease in retained_second_attempt} == {"recovery_required"}
        assert len(cap.remove) == 2
        assert len(forwarded_statuses) == 2
    finally:
        await runner_http.aclose()


@pytest.mark.parametrize("denial", ["read_only_parent", "foreign_host"])
async def test_run_child_authorizes_parent_and_host_before_reservation(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    denial: str,
) -> None:
    """Parent and Host authorization both precede Run and Host side effects."""
    from omnigent.server.routes._sessions import orchestration

    cap = register_host()
    agent_payload = await create_test_agent(
        client,
        name="owner-gated-coordinator",
        sub_agents=[{"name": "worker"}],
    )
    agent = SqlAlchemyAgentStore(db_uri).get(agent_payload["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path="/Users/alice/owner-gated",
        repositories=(("api", "api"), ("web", "web")),
    )
    root = SqlAlchemyConversationStore(db_uri).create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace.root_path,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run = run_store.create_run_idempotent(
        auth_scope="user:reader",
        actor_id="reader@example.com",
        source="api:test",
        source_event_id="owner-before-reservation",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    ).run

    async def _read_only_access(
        _user_id: str | None,
        _session_id: str,
        required_level: int,
        *_args: object,
    ) -> None:
        if required_level == LEVEL_OWNER:
            raise OmnigentError("owner required", code=ErrorCode.FORBIDDEN)

    if denial == "read_only_parent":
        monkeypatch.setattr(orchestration, "_require_access", _read_only_access)
    else:
        from omnigent.server.routes import _host_launch

        def _foreign_host(**_kwargs: object) -> None:
            raise HTTPException(status_code=403, detail="not your host")

        monkeypatch.setattr(_host_launch, "resolve_host_owner", _foreign_host)
    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent.id,
            "parent_session_id": root.id,
            "sub_agent_name": "worker",
            "title": "worker:forbidden",
            "dispatch_source_id": "sys_session_send:owner-before-reservation",
        },
    )
    if response.status_code == 201:
        await client.delete(f"/v1/sessions/{response.json()['id']}")

    assert response.status_code == 403, response.text
    assert run_store.list_tasks(run.id) == ()
    assert run_store.list_attempts(run.id) == ()
    assert cap.create == []
    assert cap.launch == []


@pytest.mark.parametrize("stop_status", ["ok", "failed"])
async def test_run_child_rolls_back_after_create_time_host_launch_failure(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    app: FastAPI,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    stop_status: str,
) -> None:
    """An unconfirmed runner stop retains the Child binding until maintenance."""
    cap = register_host(launch_status="failed", stop_status=stop_status)
    agent_payload = await create_test_agent(
        client,
        name="late-failure-coordinator",
        sub_agents=[{"name": "worker"}],
    )
    agent = SqlAlchemyAgentStore(db_uri).get(agent_payload["id"])
    assert agent is not None
    snapshot = AgentBundleSnapshot.from_agent(agent)
    conversation_store = SqlAlchemyConversationStore(db_uri)
    run_store = SqlAlchemyRunStore(db_uri)
    workspace = run_store.create_workspace(
        root_path="/Users/alice/late-failure",
        repositories=(("api", "api"), ("web", "web")),
    )
    root = conversation_store.create_conversation(
        agent_id=agent.id,
        host_id=_HOST_ID,
        workspace=workspace.root_path,
        agent_bundle_version=snapshot.bundle_version,
        agent_bundle_digest=snapshot.bundle_digest,
        agent_bundle_location=snapshot.bundle_location,
    )
    run = run_store.create_run_idempotent(
        auth_scope="user:local",
        actor_id=RESERVED_USER_LOCAL,
        source="api:test",
        source_event_id="late-host-launch-failure",
        agent_id=agent.id,
        bundle_version=snapshot.bundle_version,
        bundle_digest=snapshot.bundle_digest,
        bundle_location=snapshot.bundle_location,
        workspace_id=workspace.id,
        root_session_id=root.id,
    ).run

    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent.id,
            "parent_session_id": root.id,
            "sub_agent_name": "worker",
            "title": "worker:late failure",
            "dispatch_source_id": "sys_session_send:late-host-launch-failure",
        },
    )

    assert response.status_code >= 400, response.text
    assert "boom" in response.text
    attempts = run_store.list_attempts(run.id)
    assert len(attempts) == 1
    assert attempts[0].status.value == "failed"
    child_id = attempts[0].child_session_id
    assert len(cap.create) == 2
    if stop_status == "ok":
        assert conversation_store.get_conversation(child_id) is None
        assert run_store.list_active_worktree_leases(run.id) == ()
        assert {frame.worktree_path for frame in cap.remove} == {
            frame.target_path for frame in cap.create
        }
    else:
        child = conversation_store.get_conversation(child_id)
        assert child is not None
        assert child.runner_id is not None
        assert child.workspace is not None
        retained = run_store.list_active_worktree_leases(run.id)
        assert len(retained) == 2
        assert {lease.status.value for lease in retained} == {"recovery_required"}
        assert cap.remove == []

        from omnigent.server.routes._sessions import helpers

        async def _runner_status_alive(*_args: object, **_kwargs: object) -> str:
            return "alive"

        monkeypatch.setattr(helpers, "_query_host_runner_status", _runner_status_alive)
        stop = asyncio.Event()
        maintenance = asyncio.create_task(
            _host_worktree.maintain_attempt_worktree_leases(
                app.state.host_registry,
                stop,
                conversation_store=conversation_store,
                interval_s=0.01,
            )
        )
        try:
            async with asyncio.timeout(2):
                while len(cap.stop) < 2:
                    await asyncio.sleep(0.01)
        finally:
            stop.set()
            await maintenance
        assert cap.remove == []
        retained_child = conversation_store.get_conversation(child_id)
        assert retained_child is not None
        assert retained_child.runner_id == child.runner_id
        assert retained_child.workspace == child.workspace
        assert {lease.status.value for lease in run_store.list_active_worktree_leases(run.id)} == {
            "recovery_required"
        }

        async def _runner_status_dead(*_args: object, **_kwargs: object) -> str:
            return "dead"

        monkeypatch.setattr(helpers, "_query_host_runner_status", _runner_status_dead)
        original_recover = _host_worktree.recover_expired_attempt_worktree_leases
        concurrent_rebind_results: list[object] = []

        async def _recover_after_concurrent_rebind_attempt(**kwargs: object) -> object:
            current = conversation_store.get_conversation(child_id)
            if current is not None and not concurrent_rebind_results:
                concurrent_rebind_results.append(
                    conversation_store.compare_and_swap_host_runner_binding(
                        child_id,
                        expected_runner_id=current.runner_id,
                        expected_workspace=current.workspace,
                        host_id=current.host_id,
                        workspace=f"{current.workspace}-replacement",
                        runner_id="runner-concurrent-rebind",
                    )
                )
            return await original_recover(**kwargs)

        monkeypatch.setattr(
            _host_worktree,
            "recover_expired_attempt_worktree_leases",
            _recover_after_concurrent_rebind_attempt,
        )
        stop = asyncio.Event()
        maintenance = asyncio.create_task(
            _host_worktree.maintain_attempt_worktree_leases(
                app.state.host_registry,
                stop,
                conversation_store=conversation_store,
                interval_s=0.01,
            )
        )
        try:
            async with asyncio.timeout(2):
                while cap.remove == []:
                    await asyncio.sleep(0.01)
        finally:
            stop.set()
            await maintenance
        assert len(cap.remove) == 2
        assert concurrent_rebind_results == [None]
        assert run_store.list_active_worktree_leases(run.id) == ()
        assert conversation_store.get_conversation(child_id) is None


async def _bare_session(client: httpx.AsyncClient, name: str) -> str:
    """Create an unbound session (agent only, no host/workspace).

    :param client: The test HTTP client.
    :param name: Agent name to create.
    :returns: The new session id.
    """
    agent = await create_test_agent(client, name=name)
    resp = await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _launch(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    git: dict[str, object] | None = None,
) -> httpx.Response:
    """POST the dedicated per-session bind+launch endpoint.

    :param client: The test HTTP client.
    :param session_id: Existing session to bind.
    :param git: Optional ``git`` block. Create mode, e.g.
        ``{"branch_name": "feature/x"}``; bind mode, e.g.
        ``{"branch_name": "feature/x", "existing_worktree": True}``.
    :returns: The raw HTTP response.
    """
    body: dict[str, object] = {"session_id": session_id, "workspace": _SOURCE_REPO}
    if git is not None:
        body["git"] = git
    return await client.post(f"/v1/hosts/{_HOST_ID}/runners", json=body)


async def test_launch_runner_with_git_creates_worktree_and_persists_branch(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """``launch_runner`` with a ``git`` block creates a worktree off the
    source repo and binds the session to the worktree path + branch.

    Proves the new worktree step on the dedicated bind endpoint: the
    request's branch reaches ``host.create_worktree``, and the resulting
    worktree path + branch are persisted on the (previously unbound)
    session row via the extended ``set_host_id``. Without the new code the
    session would bind to the source repo with ``git_branch=NULL``.
    """
    cap = register_host()
    session_id = await _bare_session(client, "wt-launch-agent")

    resp = await _launch(
        client, session_id, git={"branch_name": "feature/login", "base_branch": "main"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["runner_id"]  # a runner was bound

    # The host received exactly one create-worktree frame off the source
    # repo, carrying the requested branch + base ref.
    assert len(cap.create) == 1, f"expected one create_worktree frame, got {len(cap.create)}"
    assert cap.create[0].repo_path == _SOURCE_REPO
    assert cap.create[0].branch_name == "feature/login"
    assert cap.create[0].base_branch == "main"
    # Success path: no rollback.
    assert cap.remove == [], "worktree was rolled back on a successful launch"

    # Persisted row: workspace is the worktree path (NOT the source repo),
    # git_branch is the new branch, host_id is bound. A NULL git_branch
    # here means set_host_id didn't receive/persist the branch.
    conv = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conv is not None
    assert conv.workspace == f"{_SOURCE_REPO}-worktrees/feature-login"
    assert conv.git_branch == "feature/login"
    assert conv.host_id == _HOST_ID


async def test_launch_runner_without_git_binds_source_dir_no_worktree(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """Without a ``git`` block the endpoint binds the source directory
    directly and creates no worktree (the same-directory resume path).

    Pins that the new worktree code is inert when ``git`` is omitted:
    no ``host.create_worktree`` frame, workspace stays the source repo,
    and ``git_branch`` stays NULL.
    """
    cap = register_host()
    session_id = await _bare_session(client, "no-wt-agent")

    resp = await _launch(client, session_id, git=None)
    assert resp.status_code == 200, resp.text

    assert cap.create == [], "no worktree should be created without a git block"
    conv = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conv is not None
    assert conv.workspace == _SOURCE_REPO
    assert conv.git_branch is None
    assert conv.host_id == _HOST_ID


async def test_launch_runner_with_existing_worktree_persists_without_creating(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """``git.existing_worktree`` binds the existing worktree dir and records
    its branch without creating a worktree (the existing-worktree resume path).

    The workspace is already a worktree, so no ``host.create_worktree``
    frame is sent; ``branch_name`` is persisted as ``git_branch`` so the
    sidebar shows it and the opt-in delete flow can offer to remove it.
    """
    cap = register_host()
    session_id = await _bare_session(client, "existing-wt-agent")

    resp = await _launch(
        client,
        session_id,
        git={"branch_name": "feature/existing", "existing_worktree": True},
    )
    assert resp.status_code == 200, resp.text

    assert cap.create == [], "no worktree should be created for an existing worktree"
    conv = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conv is not None
    assert conv.workspace == _SOURCE_REPO
    assert conv.git_branch == "feature/existing"
    assert conv.host_id == _HOST_ID


async def test_launch_runner_rolls_back_worktree_on_launch_failure(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """When the host fails the launch, the just-created worktree is
    rolled back AND the runner binding is cleared so the picker can retry.

    The worktree is created (status ok) but the launch reports
    ``failed`` → the endpoint returns 502, sends a
    ``host.remove_worktree`` for the created worktree, and clears the
    session's ``runner_id``. If the rollback were missing, ``cap.remove``
    would be empty; if the binding weren't cleared, ``runner_id`` would
    stay set and a retry would dead-end on the atomic ``set_runner_id``
    CAS with "session already has a runner bound" (the whole point of the
    fork-resume picker is that the user can retry after a failed bind).
    """
    cap = register_host(launch_status="failed")
    session_id = await _bare_session(client, "wt-rollback-agent")

    resp = await _launch(client, session_id, git={"branch_name": "feature/x"})

    # Launch failed → 502 (host fault), as the no-git path already does.
    assert resp.status_code == 502, resp.text
    # The worktree was created, then removed (rollback fired) for the same path.
    assert len(cap.create) == 1
    assert len(cap.remove) == 1, "expected a rollback remove_worktree frame after launch failure"
    created_path = f"{_SOURCE_REPO}-worktrees/feature-x"
    assert cap.remove[0].worktree_path == created_path
    assert cap.remove[0].delete_branch is True  # orphan branch also cleaned up

    # The session is fully unbound so the DB matches the host's actual
    # state (worktree removed) and a retry starts clean. A non-None
    # runner_id would stick the session as "already bound"; a leftover
    # workspace/git_branch would point at the deleted worktree/branch and
    # could wrongly trigger worktree-cleanup paths (git_branch IS NOT NULL).
    conv = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conv is not None
    assert conv.runner_id is None, (
        "runner_id should be cleared after a failed launch so the picker can "
        f"rebind; got {conv.runner_id!r} (retry would 400 'already has a runner bound')"
    )
    assert conv.host_id is None, f"host_id should be cleared on rollback; got {conv.host_id!r}"
    assert conv.workspace is None, (
        f"workspace should be cleared (worktree was removed); got {conv.workspace!r}"
    )
    assert conv.git_branch is None, (
        f"git_branch should be cleared (branch was removed); got {conv.git_branch!r}"
    )


async def test_launch_runner_retry_succeeds_after_failed_launch(
    register_host: RegisterHost,
    client: httpx.AsyncClient,
    db_uri: str,
) -> None:
    """A second bind succeeds after the first launch failed.

    End-to-end proof of the cleared-binding fix: a failed launch (502)
    must leave the session re-bindable. The retry creates a fresh
    worktree and binds the runner. Without clearing ``runner_id`` on the
    first failure, this retry returns 400 "session already has a runner
    bound" — the dead-end the fork-resume picker would otherwise hit.
    """
    register_host(launch_status="failed")
    session_id = await _bare_session(client, "wt-retry-agent")

    first = await _launch(client, session_id, git={"branch_name": "feature/x"})
    assert first.status_code == 502, first.text

    # Re-register the host to launch successfully this time (newest-wins
    # replaces the failing connection), then retry the bind.
    cap_ok = register_host(launch_status="launched")
    second = await _launch(client, session_id, git={"branch_name": "feature/y"})

    # Retry binds cleanly — proves runner_id was released by the failure.
    assert second.status_code == 200, second.text
    assert second.json()["runner_id"]
    assert len(cap_ok.create) == 1, "retry created a fresh worktree off the source repo"
    conv = SqlAlchemyConversationStore(db_uri).get_conversation(session_id)
    assert conv is not None
    assert conv.workspace == f"{_SOURCE_REPO}-worktrees/feature-y"
    assert conv.git_branch == "feature/y"
