#!/usr/bin/env python3
"""Validate load-project-context request and result contracts."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


STAGE_MAP = {
    "requirement-analysis": "propose",
    "proposal": "propose",
    "test-design": "propose",
    "research": "tech-design",
    "design": "tech-design",
    "implementation-frontend": "apply",
    "implementation-backend": "apply",
    "test-execution": "apply",
    "integration": "apply",
    "verification": "apply",
    "review": "apply",
}
COVERAGE = {"cross-stack", "frontend", "backend", "test", "authoritative-only"}
KNOWLEDGE_PATHS = {"knowledge_agent", "llmwiki", "project_wiki"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def required(payload: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [f"{field} is required" for field in fields if payload.get(field) in (None, "", [])]


def validate_request(payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors = required(
        payload,
        ("task_id", "workspace_root", "query", "harness_stage", "coverage", "artifact"),
    )
    stage = payload.get("harness_stage")
    if stage not in STAGE_MAP:
        errors.append("harness_stage is unsupported")
    if payload.get("coverage") not in COVERAGE:
        errors.append("coverage is unsupported")
    expert = payload.get("expert_id")
    if expert is not None and (not isinstance(expert, int) or isinstance(expert, bool) or expert not in {1, 2, 3}):
        errors.append("expert_id must be 1, 2, or 3")
    return errors, {"knowledge_stage": STAGE_MAP.get(stage)}


def validate_result(payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors = required(
        payload,
        (
            "task_id",
            "knowledge_path",
            "knowledge_path_reason",
            "knowledge_base_checked",
            "knowledge_hits",
            "matched_services",
            "coverage_check",
            "artifact",
        ),
    )
    if payload.get("knowledge_path") not in KNOWLEDGE_PATHS:
        errors.append("knowledge_path is unsupported")
    if payload.get("knowledge_base_checked") is not True:
        errors.append("knowledge_base_checked must be true for every knowledge path")
    for field in ("knowledge_hits", "matched_services"):
        if field in payload and not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    if "coverage_check" in payload and not isinstance(payload["coverage_check"], dict):
        errors.append("coverage_check must be an object")
    return errors, {}


VALIDATORS = {"request": validate_request, "result": validate_result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(VALIDATORS))
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        payload = load(args.source)
        errors, output = VALIDATORS[args.kind](payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "kind": args.kind, **output}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
