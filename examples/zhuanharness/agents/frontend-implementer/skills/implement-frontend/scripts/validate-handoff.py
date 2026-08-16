#!/usr/bin/env python3
"""Validate frontend/backend immutable implementation handoffs."""

import json
import re
import sys
from pathlib import Path
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40,64}$")
STATUSES = {"READY_FOR_INTEGRATION", "NO_CHANGE", "BLOCKED_BASE_MISMATCH", "BLOCKED_SCOPE", "HANDOFF_REF_CONFLICT", "FAILED_TEST", "FAILED_IMPLEMENTATION", "RECOVERY_REQUIRED"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("handoff must be a JSON object")
    return value


def validate(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("task_id", "role", "status", "acceptance_ids", "repositories"):
        if value.get(field) in (None, "", []):
            errors.append(f"{field} is required")
    if value.get("role") not in {"frontend", "backend"}:
        errors.append("role must be frontend or backend")
    if value.get("status") not in STATUSES:
        errors.append("status is invalid")
    repositories = value.get("repositories")
    if not isinstance(repositories, list):
        errors.append("repositories must be an array")
        repositories = []
    for index, repo in enumerate(repositories):
        if not isinstance(repo, dict):
            errors.append(f"repositories[{index}] must be an object")
            continue
        for field in ("repository_id", "expected_base_sha", "output_sha", "handoff_ref", "changed_paths", "clean", "checks"):
            if field not in repo or repo[field] in (None, ""):
                errors.append(f"repositories[{index}].{field} is required")
        for field in ("expected_base_sha", "output_sha"):
            if not SHA.fullmatch(str(repo.get(field, ""))):
                errors.append(f"repositories[{index}].{field} must be a full lowercase hex SHA")
        ref = str(repo.get("handoff_ref", ""))
        if not ref.startswith("refs/zhuanspec/"):
            errors.append(f"repositories[{index}].handoff_ref must be a semantic zhuanspec ref")
        if repo.get("clean") is not True:
            errors.append(f"repositories[{index}] must be clean")
        checks = repo.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"repositories[{index}].checks must be non-empty")
            checks = []
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict):
                errors.append(f"repositories[{index}].checks[{check_index}] must be an object")
                continue
            for field in ("command", "exit_code", "observed_at", "log_anchor"):
                if field not in check or check[field] in (None, ""):
                    errors.append(f"repositories[{index}].checks[{check_index}].{field} is required")
            if check.get("exit_code") != 0:
                errors.append(f"repositories[{index}].checks[{check_index}] must pass")
            if "sha256=" not in str(check.get("log_anchor", "")):
                errors.append(f"repositories[{index}].checks[{check_index}].log_anchor must include sha256")
    if value.get("status") == "READY_FOR_INTEGRATION" and not repositories:
        errors.append("READY_FOR_INTEGRATION requires repositories")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-handoff.py <handoff.json|->", file=sys.stderr)
        return 2
    try:
        errors = validate(load(sys.argv[1]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
