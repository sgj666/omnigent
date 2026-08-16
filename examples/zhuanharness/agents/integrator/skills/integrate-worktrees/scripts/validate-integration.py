#!/usr/bin/env python3
"""Validate worktree integration contracts using only Python stdlib."""

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

STATUSES = {"INTEGRATED", "INTEGRATION_CONFLICT", "INTEGRATION_FAILED", "BLOCKED_BASE_MISMATCH", "INVALID_HANDOFF"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def required(payload: dict[str, Any], fields: tuple[str, ...], prefix: str = "") -> list[str]:
    return [f"{prefix}{field} is required" for field in fields if payload.get(field) in (None, "", [])]


def owned(path: str, scopes: list[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(candidate == PurePosixPath(scope) or PurePosixPath(scope) in candidate.parents for scope in scopes)


def validate_request(payload: dict[str, Any]) -> list[str]:
    errors = required(payload, ("task_id", "change_id", "attempt_root", "control_repository_id", "base_vector", "handoffs", "task_order", "artifact_snapshot", "required_checks", "integration_attempt", "output_manifest", "hook_context"))
    base_vector = payload.get("base_vector", [])
    handoffs = payload.get("handoffs", [])
    if not isinstance(base_vector, list) or not isinstance(handoffs, list):
        return errors + ["base_vector and handoffs must be arrays"]
    bases = {item.get("repository_id"): item.get("base_sha") for item in base_vector if isinstance(item, dict)}
    task_order = payload.get("task_order", [])
    handoff_tasks: list[str] = []
    for item in handoffs:
        if not isinstance(item, dict):
            errors.append("each handoff must be an object")
            continue
        errors.extend(required(item, ("task_id", "repository_id", "ref", "output_sha", "base_sha", "commits", "changed_paths", "owned_paths"), "handoff "))
        handoff_tasks.append(item.get("task_id"))
        if item.get("base_sha") != bases.get(item.get("repository_id")):
            errors.append(f"handoff {item.get('task_id')} base_sha does not match base_vector")
        expected_prefix = f"refs/zhuanspec/{payload.get('change_id')}/handoff/"
        if not str(item.get("ref", "")).startswith(expected_prefix):
            errors.append(f"handoff {item.get('task_id')} ref is outside change namespace")
        for path in item.get("changed_paths", []):
            if not owned(path, item.get("owned_paths", [])):
                errors.append(f"handoff {item.get('task_id')} changed path outside owned_paths: {path}")
    if len(task_order) != len(set(task_order)):
        errors.append("task_order contains duplicates")
    if set(task_order) != set(handoff_tasks):
        errors.append("task_order must cover every handoff task")
    return errors


def validate_result(payload: dict[str, Any]) -> list[str]:
    errors = required(payload, ("change_id", "status", "base_vector", "input_handoffs", "candidate_vector", "manifest", "applied_commits", "checks"))
    for field in ("conflicts", "unchanged_repositories"):
        if field not in payload:
            errors.append(f"{field} is required")
        elif not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    if payload.get("status") not in STATUSES:
        errors.append("status is unsupported")
    if payload.get("status") == "INTEGRATED":
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict) or manifest.get("status") != "COMPLETE":
            errors.append("INTEGRATED requires COMPLETE manifest")
        bases = {item.get("repository_id") for item in payload.get("base_vector", []) if isinstance(item, dict)}
        candidates = {item.get("repository_id") for item in payload.get("candidate_vector", []) if isinstance(item, dict)}
        if bases != candidates:
            errors.append("candidate_vector must contain the complete base repository set")
        for check in payload.get("checks", []):
            if not isinstance(check, dict) or check.get("exit_code") != 0:
                errors.append("INTEGRATED requires every check exit_code 0")
        if payload.get("conflicts"):
            errors.append("INTEGRATED cannot contain conflicts")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("request", "result"))
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        payload = load(args.source)
        errors = validate_request(payload) if args.kind == "request" else validate_result(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "kind": args.kind}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
