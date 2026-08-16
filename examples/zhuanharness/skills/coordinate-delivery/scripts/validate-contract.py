#!/usr/bin/env python3
"""Validate zhuanharness Coordinator JSON contracts using only stdlib."""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


STATES = [
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
LEGAL_TRANSITIONS = {
    "intake": "preflight",
    "preflight": "requirement",
    "requirement": "research",
    "research": "proposal",
    "proposal": "planning",
    "planning": "implementation",
    "implementation": "integration",
    "integration": "testing",
    "testing": "verification",
    "verification": "review",
    "review": "knowledge_close",
    "knowledge_close": "archive",
    "archive": "pending_delivery",
    "pending_delivery": "delivered",
}
REQUIRED_TRANSITION_EVIDENCE = {
    "preflight": {"run-request"},
    "requirement": {"harness-precheck"},
    "research": {"requirement-manifest"},
    "proposal": {"research-artifact"},
    "planning": {"proposal-manifest"},
    "implementation": {"plan-approval"},
    "integration": {"implementation-handoff"},
    "testing": {"candidate-vector"},
    "verification": {"test-result"},
    "review": {"verification-result"},
    "knowledge_close": {"review-result"},
    "archive": {"knowledge-closure"},
    "pending_delivery": {"archive-result"},
    "delivered": {"human-approval"},
}
RESULT_STATUSES = {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"}
DECISION_KINDS = {"ANSWERED", "FACT_GAP", "HUMAN_DECISION"}
TASK_MODES = {"read", "control-plane-write", "worktree-write"}
HOOK_MODES = {"DEFERRED", "ENFORCED"}
WORK_TYPES = {
    "requirement-review",
    "research",
    "proposal",
    "implementation",
    "test",
    "verification",
    "review",
    "knowledge-curation",
    "archive",
    "coordination",
}


def load_payload(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def require_nonempty(payload: dict[str, Any], fields: list[str], errors: list[str]) -> None:
    for field in fields:
        if field not in payload or payload[field] in (None, "", []):
            errors.append(f"{field} is required")


def parse_timestamp(value: Any, field: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field} is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} must be an ISO 8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a timezone")
        return None
    return parsed


def validate_harness_precheck(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_nonempty(payload, ["run_id", "status", "artifact"], errors)
    status = payload.get("status")
    if status not in {"READY", "BLOCKED"}:
        errors.append("status must be READY or BLOCKED")
    elif status == "BLOCKED" and not payload.get("blocked_stage"):
        errors.append("blocked_stage is required when status is BLOCKED")
    for resource in ("workers", "skills"):
        available = payload.get(f"available_{resource}")
        required = payload.get(f"required_{resource}")
        missing = payload.get(f"missing_{resource}")
        for field, value in (
            (f"available_{resource}", available),
            (f"required_{resource}", required),
            (f"missing_{resource}", missing),
        ):
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"{field} must be an array of strings")
        if all(isinstance(value, list) for value in (available, required, missing)):
            expected = sorted(set(required) - set(available))
            if sorted(set(missing)) != expected:
                errors.append(f"missing_{resource} must equal required_{resource} - available_{resource}")
    has_missing = bool(payload.get("missing_workers") or payload.get("missing_skills"))
    hooks_mode = payload.get("hooks_mode", "ENFORCED")
    if hooks_mode not in HOOK_MODES:
        errors.append("hooks_mode must be DEFERRED or ENFORCED")
    if hooks_mode == "DEFERRED" and not payload.get("hooks_deferred_reason"):
        errors.append("hooks_deferred_reason is required when hooks_mode=DEFERRED")
    hook_installer = payload.get("hook_installer")
    required_hook_events = payload.get("required_hook_events")
    available_hook_events = payload.get("available_hook_events")
    missing_hook_events = payload.get("missing_hook_events")
    for field, value in (
        ("required_hook_events", required_hook_events),
        ("available_hook_events", available_hook_events),
        ("missing_hook_events", missing_hook_events),
    ):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{field} must be an array of strings")
    if all(
        isinstance(value, list)
        for value in (required_hook_events, available_hook_events, missing_hook_events)
    ):
        expected_missing_hooks = sorted(set(required_hook_events) - set(available_hook_events))
        if sorted(set(missing_hook_events)) != expected_missing_hooks:
            errors.append(
                "missing_hook_events must equal required_hook_events - available_hook_events"
            )
    hook_blocked = False
    if hooks_mode == "ENFORCED":
        if hook_installer != "zhuanspec init --harness":
            errors.append("hook_installer must be zhuanspec init --harness")
        if payload.get("project_settings_enabled") is not True:
            errors.append("project settings must remain enabled for project hooks")
        if payload.get("attempt_bootstrap_available") is not True:
            errors.append("attempt bootstrap must materialize harness assets before worker startup")
        hook_blocked = (
            hook_installer != "zhuanspec init --harness"
            or payload.get("project_settings_enabled") is not True
            or payload.get("attempt_bootstrap_available") is not True
            or bool(missing_hook_events)
        )
    if (has_missing or hook_blocked) and status != "BLOCKED":
        errors.append("precheck with missing capabilities or hooks must be BLOCKED")
    if not has_missing and not hook_blocked and status == "BLOCKED":
        errors.append("BLOCKED precheck requires a missing capability or hook")
    return errors


def validate_task_packet(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_nonempty(
        payload,
        [
            "task_id",
            "requirement_id",
            "worker",
            "objective",
            "deliverables",
            "acceptance",
            "workspace_root",
            "attempt_root",
            "task_mode",
            "attempt",
        ],
        errors,
    )
    for field in ("inputs", "deliverables", "acceptance"):
        if field in payload and not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    task_mode = payload.get("task_mode")
    if task_mode not in TASK_MODES:
        errors.append("task_mode must be read, control-plane-write, or worktree-write")
    elif task_mode == "worktree-write":
        require_nonempty(payload, ["worktree_root", "write_scope"], errors)
        if "write_scope" in payload and not isinstance(payload["write_scope"], list):
            errors.append("write_scope must be an array")
    elif task_mode == "control-plane-write":
        require_nonempty(payload, ["write_scope"], errors)
        if "write_scope" in payload and not isinstance(payload["write_scope"], list):
            errors.append("write_scope must be an array")
        if payload.get("worktree_root"):
            errors.append("control-plane-write tasks must not declare worktree_root")
    elif payload.get("write_scope") or payload.get("worktree_root"):
        errors.append("read tasks must not declare worktree_root or write_scope")
    hook_context = payload.get("hook_context")
    if not isinstance(hook_context, dict):
        errors.append("hook_context is required")
    else:
        hook_status = hook_context.get("status")
        if hook_status not in {"READY", "DEFERRED"}:
            errors.append("hook_context.status must be READY or DEFERRED before dispatch")
        if hook_context.get("attempt_root") != payload.get("attempt_root"):
            errors.append("hook_context.attempt_root must match attempt_root")
        if hook_status == "READY":
            if hook_context.get("project_settings_loaded") is not True:
                errors.append("hook_context project settings must be loaded")
            if hook_context.get("hooks_materialized") is not True:
                errors.append("hook_context hooks must be materialized")
            if not hook_context.get("event_shard"):
                errors.append("hook_context.event_shard is required")
        elif hook_status == "DEFERRED" and not hook_context.get("reason"):
            errors.append("hook_context.reason is required when status=DEFERRED")
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append("attempt must be a positive integer")
    if payload.get("parallel_group"):
        contract = payload.get("shared_contract")
        if not isinstance(contract, dict) or contract.get("status") != "FROZEN":
            errors.append("parallel tasks require shared_contract.status=FROZEN")
        elif not contract.get("artifact"):
            errors.append("a FROZEN shared contract requires an artifact")
    return errors


def validate_result_envelope(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_nonempty(payload, ["task_id", "attempt", "status", "summary"], errors)
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append("attempt must be a positive integer")
    status = payload.get("status")
    if status not in RESULT_STATUSES:
        errors.append("status must be DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED")
    summary = payload.get("summary")
    if isinstance(summary, str) and len(summary) > 240:
        errors.append("summary must be at most 240 characters; move details to the artifact")
    elif summary is not None and not isinstance(summary, str):
        errors.append("summary must be a string")
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        errors.append("questions must be an array")
    if status in {"DONE", "DONE_WITH_CONCERNS"}:
        work_type = payload.get("work_type")
        if work_type not in WORK_TYPES:
            errors.append("completed results require a supported work_type")
        attempt_started_at = parse_timestamp(
            payload.get("attempt_started_at"), "attempt_started_at", errors
        )
        if not payload.get("artifact"):
            errors.append("completed results require an artifact")
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("completed results require fresh evidence")
        else:
            for index, item in enumerate(evidence):
                if not isinstance(item, dict) or not item.get("kind"):
                    errors.append(f"evidence[{index}] requires kind")
                    continue
                if item.get("attempt") != attempt:
                    errors.append(f"evidence[{index}].attempt must match envelope attempt")
                produced_at = parse_timestamp(
                    item.get("produced_at"), f"evidence[{index}].produced_at", errors
                )
                if attempt_started_at and produced_at and produced_at < attempt_started_at:
                    errors.append(f"evidence[{index}] predates the current attempt")
                if item["kind"] == "test":
                    if not item.get("command") or "exit_code" not in item or not item.get("summary"):
                        errors.append(
                            f"evidence[{index}] test requires command, exit_code, and summary"
                        )
                    elif item.get("exit_code") != 0:
                        errors.append(f"evidence[{index}] test exit_code must be 0")
                elif not item.get("ref"):
                    errors.append(f"evidence[{index}] requires ref")
        evidence_items = evidence if isinstance(evidence, list) else []
        if work_type == "implementation" and not any(
            isinstance(item, dict) and item.get("kind") in {"commit", "change"} and item.get("ref")
            for item in evidence_items
        ):
            errors.append("implementation results require a commit or change reference")
    return errors


def validate_artifact_record(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_nonempty(
        payload,
        [
            "artifact_id",
            "run_id",
            "task_id",
            "type",
            "path",
            "content_hash",
            "created_at",
            "producer_attempt",
        ],
        errors,
    )
    path = payload.get("path")
    if isinstance(path, str) and (
        not path.startswith("zhuanspec/changes/")
        or path.startswith("/")
        or ".." in Path(path).parts
    ):
        errors.append("path must be a relative path under zhuanspec/changes/")
    content_hash = payload.get("content_hash")
    if isinstance(content_hash, str) and re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
        errors.append("content_hash must be a lowercase SHA-256 hex digest")
    attempt = payload.get("producer_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append("producer_attempt must be a positive integer")
    parse_timestamp(payload.get("created_at"), "created_at", errors)
    return errors


def validate_decision_frontier(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return ["items must be a non-empty array"]
    seen: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("id", "kind", "question", "route"):
            if not item.get(field):
                errors.append(f"{prefix}.{field} is required")
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in seen:
                errors.append(f"{prefix}.id must be unique")
            seen.add(item_id)
        kind = item.get("kind")
        route = item.get("route")
        if kind not in DECISION_KINDS:
            errors.append(f"{prefix}.kind is unsupported")
        elif kind == "FACT_GAP" and route != "research-engineer":
            errors.append(f"{prefix} FACT_GAP must route to research-engineer")
        elif kind == "ANSWERED" and route != "coordinator":
            errors.append(f"{prefix} ANSWERED must route to coordinator")
        elif kind == "HUMAN_DECISION":
            if route != "user":
                errors.append(f"{prefix} HUMAN_DECISION must route to user")
            for field in ("recommendation", "consequence"):
                if not item.get(field):
                    errors.append(f"{prefix}.{field} is required for HUMAN_DECISION")
    return errors


def validate_transition(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_nonempty(
        payload,
        ["transition_id", "run_id", "idempotency_key"],
        errors,
    )
    expected_version = payload.get("expected_version")
    current_version = payload.get("current_version")
    if (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or expected_version < 0
    ):
        errors.append("expected_version must be a non-negative integer")
    if (
        not isinstance(current_version, int)
        or isinstance(current_version, bool)
        or current_version < 0
    ):
        errors.append("current_version must be a non-negative integer")
    elif isinstance(expected_version, int) and current_version != expected_version:
        errors.append("expected_version is stale")
    source = payload.get("from")
    target = payload.get("to")
    if source not in STATES:
        errors.append("from is not a known state")
    if target not in STATES:
        errors.append("to is not a known state")
    if errors:
        return errors
    transition_id = payload.get("transition_id")
    if payload.get("idempotency_key") != transition_id:
        errors.append("idempotency_key must equal transition_id")
    if source == target:
        if payload.get("applied_transition_id") != transition_id:
            errors.append("self-transition is only valid as an idempotent replay")
    elif LEGAL_TRANSITIONS.get(source) != target:
        errors.append(f"illegal transition: {source} -> {target}")
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        errors.append("evidence must be an array")
        return errors
    evidence_kinds: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        if not item.get("kind"):
            errors.append(f"evidence[{index}].kind is required")
        else:
            evidence_kinds.add(item["kind"])
        if not item.get("ref"):
            errors.append(f"evidence[{index}].ref is required")
    required_kinds = REQUIRED_TRANSITION_EVIDENCE.get(target, set())
    if required_kinds and not required_kinds.intersection(evidence_kinds):
        errors.append(
            f"transition to {target} requires evidence kind: "
            + " or ".join(sorted(required_kinds))
        )
    return errors


VALIDATORS = {
    "artifact-record": validate_artifact_record,
    "decision-frontier": validate_decision_frontier,
    "harness-precheck": validate_harness_precheck,
    "task-packet": validate_task_packet,
    "result-envelope": validate_result_envelope,
    "transition": validate_transition,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(VALIDATORS))
    parser.add_argument("source", help="JSON file path, or - for stdin")
    args = parser.parse_args()
    try:
        payload = load_payload(args.source)
        errors = VALIDATORS[args.kind](payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "kind": args.kind}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
