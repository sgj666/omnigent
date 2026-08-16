#!/usr/bin/env python3
"""Validate knowledge curation contracts using only Python stdlib."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CATEGORIES = {"troubleshooting", "best-practices", "implicit-conventions", "deprecated"}
ACTIONS = {"create", "update", "deprecate", "reject"}
STATUSES = {"CURATED", "NO_CANDIDATES", "NEEDS_USER_DECISION", "INVALID"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def required(item: dict[str, Any], fields: tuple[str, ...], prefix: str = "") -> list[str]:
    return [f"{prefix}{field} is required" for field in fields if item.get(field) in (None, "", [])]


def validate_candidates(payload: dict[str, Any]) -> list[str]:
    errors = required(payload, ("change_id", "candidates"))
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return errors + ["candidates must be an array"]
    ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            errors.append("each candidate must be an object")
            continue
        errors.extend(required(item, ("id", "category", "title", "claim", "source_change", "evidence_refs", "confidence", "policy_impact", "sensitive", "action"), "candidate "))
        candidate_id = item.get("id")
        if candidate_id in ids:
            errors.append(f"duplicate candidate id: {candidate_id}")
        ids.add(candidate_id)
        if item.get("category") not in CATEGORIES:
            errors.append(f"candidate {candidate_id} category is unsupported")
        if item.get("action") not in ACTIONS:
            errors.append(f"candidate {candidate_id} action is unsupported")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            errors.append(f"candidate {candidate_id} confidence must be between 0 and 1")
        if item.get("action") != "reject" and confidence is not None and confidence < 0.8:
            errors.append(f"candidate {candidate_id} write action requires confidence >= 0.8")
        if item.get("action") != "reject" and not item.get("evidence_refs"):
            errors.append(f"candidate {candidate_id} write action requires evidence_refs")
        if (item.get("policy_impact") or item.get("sensitive") or item.get("action") == "deprecate") and not item.get("decision_required"):
            errors.append(f"candidate {candidate_id} requires human decision")
    return errors


def validate_result(payload: dict[str, Any]) -> list[str]:
    errors = required(payload, ("change_id", "status", "index_path", "evidence_refs"))
    for field in ("created", "updated", "deprecated", "rejected", "decision_required"):
        if field not in payload:
            errors.append(f"{field} is required")
    if payload.get("status") not in STATUSES:
        errors.append("status is unsupported")
    sets: list[set[str]] = []
    for field in ("created", "updated", "deprecated", "rejected", "decision_required"):
        value = payload.get(field, [])
        if not isinstance(value, list):
            errors.append(f"{field} must be an array")
            continue
        sets.append(set(value))
    seen: set[str] = set()
    for current in sets:
        overlap = seen & current
        if overlap:
            errors.append(f"candidate appears in multiple result sets: {sorted(overlap)}")
        seen.update(current)
    if payload.get("status") == "NEEDS_USER_DECISION" and not payload.get("decision_required"):
        errors.append("NEEDS_USER_DECISION requires decision_required candidates")
    if payload.get("status") == "CURATED" and not any(payload.get(field) for field in ("created", "updated", "deprecated")):
        errors.append("CURATED requires at least one write result")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("candidates", "result"))
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        payload = load(args.source)
        errors = validate_candidates(payload) if args.kind == "candidates" else validate_result(payload)
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
