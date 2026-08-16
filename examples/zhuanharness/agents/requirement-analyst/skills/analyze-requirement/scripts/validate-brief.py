#!/usr/bin/env python3
"""Validate a Requirement Analyst input brief."""

import json
import sys
from pathlib import Path
from typing import Any


def read_brief(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("brief must be a JSON object")
    return value


def validate(brief: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "task_id",
        "requirement_id",
        "change_id",
        "workspace_root",
        "attempt_root",
        "goal",
        "artifact_refs",
        "hook_context",
    )
    for field in required:
        if brief.get(field) in (None, "", []):
            errors.append(f"{field} is required")
    for field in ("known_scope", "existing_decisions", "artifact_refs"):
        if field not in brief or not isinstance(brief[field], list):
            errors.append(f"{field} must be an array")
    hook_context = brief.get("hook_context")
    if not isinstance(hook_context, dict):
        errors.append("hook_context must be an object")
    elif hook_context.get("status") not in {"READY", "DEFERRED"}:
        errors.append("hook_context.status must be READY or DEFERRED")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-brief.py <brief.json|->", file=sys.stderr)
        return 2
    try:
        errors = validate(read_brief(sys.argv[1]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
