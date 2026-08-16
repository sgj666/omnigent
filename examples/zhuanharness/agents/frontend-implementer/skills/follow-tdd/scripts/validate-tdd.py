#!/usr/bin/env python3
"""Validate a zhuanharness TDD evidence document."""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40,64}$")
MODES = {"required", "conditional", "exempt"}
SOURCES = {"project", "proposal", "user-decision"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return value


def timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def validate(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("task_id", "candidate_sha", "policy", "cycles"):
        if value.get(field) in (None, "", []):
            errors.append(f"{field} is required")
    if not SHA.fullmatch(str(value.get("candidate_sha", ""))):
        errors.append("candidate_sha must be a full lowercase hex SHA")
    policy = value.get("policy")
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
        policy = {}
    if policy.get("mode") not in MODES:
        errors.append("policy.mode is invalid")
    if policy.get("source") not in SOURCES:
        errors.append("policy.source is invalid")
    if not policy.get("reason"):
        errors.append("policy.reason is required")
    cycles = value.get("cycles")
    if not isinstance(cycles, list):
        errors.append("cycles must be an array")
        cycles = []
    if policy.get("mode") == "required" and not cycles:
        errors.append("required TDD must include at least one RED/GREEN cycle")
    for index, cycle in enumerate(cycles):
        if not isinstance(cycle, dict):
            errors.append(f"cycles[{index}] must be an object")
            continue
        for field in ("acceptance_id", "public_seam", "red", "green"):
            if cycle.get(field) in (None, "", []):
                errors.append(f"cycles[{index}].{field} is required")
        red, green = cycle.get("red"), cycle.get("green")
        for phase, record in (("red", red), ("green", green)):
            if not isinstance(record, dict):
                continue
            for field in ("command", "exit_code", "observed_at", "log_anchor"):
                if field not in record or record[field] in (None, ""):
                    errors.append(f"cycles[{index}].{phase}.{field} is required")
            if not timestamp(record.get("observed_at")):
                errors.append(f"cycles[{index}].{phase}.observed_at must include timezone")
            anchor = str(record.get("log_anchor", ""))
            if "sha256=" not in anchor or anchor.startswith("/"):
                errors.append(f"cycles[{index}].{phase}.log_anchor must be persistent and digested")
        if isinstance(red, dict):
            if not isinstance(red.get("exit_code"), int) or red.get("exit_code") == 0:
                errors.append(f"cycles[{index}].red.exit_code must be non-zero")
            if not red.get("failure_reason"):
                errors.append(f"cycles[{index}].red.failure_reason is required")
        if isinstance(green, dict) and green.get("exit_code") != 0:
            errors.append(f"cycles[{index}].green.exit_code must be zero")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-tdd.py <evidence.json|->", file=sys.stderr)
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
