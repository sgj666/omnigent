#!/usr/bin/env python3
"""Validate proposal input/output contracts using only Python stdlib."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUSES = {"READY", "NEEDS_RESEARCH", "NEEDS_USER_DECISION", "INVALID"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def missing(payload: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [f"{field} is required" for field in fields if payload.get(field) in (None, "", [])]


def validate_input(payload: dict[str, Any]) -> list[str]:
    errors = missing(payload, ("task_id", "requirement_id", "change_id", "workspace_root", "attempt_root", "requirement_manifest", "research_artifact_refs", "decision_refs", "spec_refs", "hook_context"))
    manifest = payload.get("requirement_manifest")
    if isinstance(manifest, dict) and manifest.get("status") != "READY":
        errors.append("requirement_manifest status must be READY")
    elif not isinstance(manifest, dict):
        errors.append("requirement_manifest must be an object")
    for field in ("research_artifact_refs", "decision_refs", "spec_refs"):
        if field in payload and not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    return errors


def cycle(tasks: list[dict[str, Any]]) -> bool:
    graph = {task.get("id"): task.get("blocked_by", []) for task in tasks if isinstance(task, dict)}
    visiting: set[str] = set()
    done: set[str] = set()
    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        if any(dep in graph and visit(dep) for dep in graph.get(node, [])):
            return True
        visiting.remove(node)
        done.add(node)
        return False
    return any(visit(node) for node in graph)


def validate_output(payload: dict[str, Any]) -> list[str]:
    errors = missing(payload, ("change_id", "status", "requirements", "acceptance_ids", "tasks", "shared_contracts", "artifacts", "validation"))
    if payload.get("status") not in STATUSES:
        errors.append("status is unsupported")
    tasks = payload.get("tasks", [])
    if not isinstance(tasks, list):
        return errors + ["tasks must be an array"]
    ids = {task.get("id") for task in tasks if isinstance(task, dict)}
    covered: set[str] = set()
    contracts = {item.get("id"): item for item in payload.get("shared_contracts", []) if isinstance(item, dict)}
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("each task must be an object")
            continue
        errors.extend(f"task {error}" for error in missing(task, ("id", "deliverable", "acceptance_ids", "worker_packets")))
        if "blocked_by" not in task:
            errors.append(f"task {task.get('id')} blocked_by is required")
        for dep in task.get("blocked_by", []):
            if dep not in ids:
                errors.append(f"task {task.get('id')} has unknown blocker {dep}")
        covered.update(task.get("acceptance_ids", []))
        packets = task.get("worker_packets", [])
        roles = {packet.get("role") for packet in packets if isinstance(packet, dict)}
        if {"frontend", "backend"}.issubset(roles) and task.get("parallel"):
            contract = contracts.get(task.get("shared_contract_id"))
            if not contract or contract.get("status") != "FROZEN":
                errors.append(f"task {task.get('id')} parallel frontend/backend requires FROZEN shared contract")
    if cycle(tasks):
        errors.append("task dependency graph contains a cycle")
    if payload.get("status") == "READY":
        absent = set(payload.get("acceptance_ids", [])) - covered
        if absent:
            errors.append(f"READY has uncovered acceptance ids: {sorted(absent)}")
        validation = payload.get("validation")
        if not isinstance(validation, dict) or validation.get("exit_code") != 0:
            errors.append("READY requires strict validation exit_code 0")
    artifacts = payload.get("artifacts")
    required_artifacts = {"proposal", "design", "tasks", "specs"}
    if not isinstance(artifacts, dict) or not required_artifacts.issubset(artifacts):
        errors.append("artifacts must contain proposal, design, tasks, and specs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("input", "output"))
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        payload = load(args.source)
        errors = validate_input(payload) if args.kind == "input" else validate_output(payload)
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
