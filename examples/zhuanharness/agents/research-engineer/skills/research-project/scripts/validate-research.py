#!/usr/bin/env python3
"""Validate Research Packet and result using only Python stdlib."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STATUSES = {"ANSWERED", "PARTIAL", "BLOCKED_EVIDENCE"}
KINDS = {"source_fact", "test_assertion", "knowledge_claim", "inference"}
VERIFICATIONS = {"verified", "contradicted", "stale", "unresolved"}


def load(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def missing(payload: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [f"{field} is required" for field in fields if payload.get(field) in (None, "", [])]


def request(payload: dict[str, Any]) -> list[str]:
    errors = missing(payload, ("task_id", "research_id", "requirement_id", "change_id", "workspace_root", "attempt_root", "question", "acceptance_ids", "artifact_refs", "output_artifact", "hook_context"))
    for field in ("acceptance_ids", "artifact_refs"):
        if field in payload and not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    if "hook_context" in payload and not isinstance(payload["hook_context"], dict):
        errors.append("hook_context must be an object")
    return errors


def result(payload: dict[str, Any]) -> list[str]:
    errors = missing(payload, ("task_id", "research_id", "status", "question", "findings", "repositories_checked", "artifacts"))
    for field in ("conflicts", "unknowns", "decision_gaps"):
        if field not in payload:
            errors.append(f"{field} is required")
    if payload.get("status") not in STATUSES:
        errors.append("status is unsupported")
    for field in ("findings", "conflicts", "unknowns", "decision_gaps", "repositories_checked"):
        if field in payload and not isinstance(payload[field], list):
            errors.append(f"{field} must be an array")
    ids: set[str] = set()
    for item in payload.get("findings", []):
        if not isinstance(item, dict):
            errors.append("each finding must be an object")
            continue
        errors.extend(f"finding {error}" for error in missing(item, ("id", "statement", "kind", "confidence", "source_refs", "code_anchors", "affects", "verification")))
        finding_id = item.get("id")
        if finding_id in ids:
            errors.append(f"duplicate finding id: {finding_id}")
        ids.add(finding_id)
        if item.get("kind") not in KINDS:
            errors.append(f"finding {finding_id} kind is unsupported")
        if item.get("verification") not in VERIFICATIONS:
            errors.append(f"finding {finding_id} verification is unsupported")
        anchors = item.get("code_anchors", [])
        if item.get("kind") == "source_fact" and item.get("affects") and not anchors:
            errors.append(f"finding {finding_id} source_fact affecting delivery requires code_anchors")
    if payload.get("status") == "ANSWERED" and payload.get("unknowns"):
        errors.append("ANSWERED cannot contain unresolved unknowns")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts.get("json") or not artifacts.get("report"):
        errors.append("artifacts must contain json and report")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("request", "result"))
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        payload = load(args.source)
        errors = request(payload) if args.kind == "request" else result(payload)
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
