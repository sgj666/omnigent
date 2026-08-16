#!/usr/bin/env python3
"""Validate a zhuanharness Requirement Manifest."""

import json
import sys
from pathlib import Path
from typing import Any


STATUSES = {"READY", "NEEDS_RESEARCH", "NEEDS_USER_DECISION", "NEEDS_SCOPE_REWORK"}
SPLIT_BASES = {"business-capability", "delivery-slice"}
ISSUE_CATEGORIES = {
    "FACT_GAP",
    "BUSINESS_DECISION",
    "SCOPE_CONFLICT",
    "CONTRACT_RISK",
    "ACCEPTANCE_GAP",
    "SECURITY_RISK",
    "DEPENDENCY_RISK",
}
USER_DECISION_KINDS = {
    "business_semantics",
    "scope_choice",
    "compatibility_tradeoff",
    "authorization",
    "irreversible_decision",
}


def read_manifest(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value


def require_fields(value: dict[str, Any], fields: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for field in fields:
        if field not in value or value[field] in (None, "", []):
            errors.append(f"{prefix}{field} is required")


def require_array(manifest: dict[str, Any], field: str, errors: list[str]) -> list[Any]:
    value = manifest.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    return value


def collect_objects(items: list[Any], name: str, errors: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{name}[{index}] must be an object")
        else:
            result.append(item)
    return result


def unique_ids(items: list[dict[str, Any]], name: str, errors: list[str]) -> set[str]:
    values: set[str] = set()
    for index, item in enumerate(items):
        item_id = item.get("id")
        if not item_id:
            errors.append(f"{name}[{index}].id is required")
        elif item_id in values:
            errors.append(f"duplicate {name} id: {item_id}")
        else:
            values.add(item_id)
    return values


def validate(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    require_fields(manifest, ("requirement_id", "status", "summary", "split_basis", "capabilities", "artifacts"), "", errors)
    if manifest.get("status") not in STATUSES:
        errors.append("status is invalid")
    if manifest.get("split_basis") not in SPLIT_BASES:
        errors.append("split_basis must be business-capability or delivery-slice")
    summary = manifest.get("summary")
    if isinstance(summary, str) and len(summary) > 240:
        errors.append("summary must be at most 240 characters")

    capabilities = collect_objects(require_array(manifest, "capabilities", errors), "capabilities", errors)
    criteria = collect_objects(require_array(manifest, "acceptance_criteria", errors), "acceptance_criteria", errors)
    issues = collect_objects(require_array(manifest, "issues", errors), "issues", errors)
    research = collect_objects(require_array(manifest, "research_requests", errors), "research_requests", errors)
    decisions = collect_objects(require_array(manifest, "user_decisions", errors), "user_decisions", errors)
    traceability = collect_objects(require_array(manifest, "traceability", errors), "traceability", errors)

    capability_ids = unique_ids(capabilities, "capabilities", errors)
    criteria_ids = unique_ids(criteria, "acceptance_criteria", errors)
    issue_ids = unique_ids(issues, "issues", errors)
    unique_ids(research, "research_requests", errors)
    unique_ids(decisions, "user_decisions", errors)

    for item in criteria:
        require_fields(item, ("id", "statement", "source_refs"), "acceptance_criteria.", errors)
        if item.get("observable") is not True:
            errors.append(f"acceptance criterion {item.get('id')} must be observable")
    for capability in capabilities:
        require_fields(capability, ("id", "title", "objective", "acceptance_criteria", "source_refs"), "capability.", errors)
        references = capability.get("acceptance_criteria")
        if not isinstance(references, list) or not references:
            errors.append(f"capability {capability.get('id')} requires acceptance criteria")
        elif unknown := set(references) - criteria_ids:
            errors.append(f"capability {capability.get('id')} references unknown acceptance criteria: {sorted(unknown)}")

    issue_by_id = {item.get("id"): item for item in issues if item.get("id")}
    fact_issue_ids = {
        item_id for item_id, item in issue_by_id.items() if item.get("category") == "FACT_GAP"
    }
    for item in issues:
        require_fields(item, ("id", "category", "summary"), "issue.", errors)
        if item.get("category") not in ISSUE_CATEGORIES:
            errors.append(f"issue {item.get('id')} has invalid category")

    research_issue_ids: set[str] = set()
    for request in research:
        require_fields(request, ("id", "issue_id", "question", "expected_evidence"), "research_request.", errors)
        issue_id = request.get("issue_id")
        if issue_id not in issue_ids:
            errors.append(f"research request references unknown issue: {issue_id}")
        research_issue_ids.add(issue_id)
    missing_research = fact_issue_ids - research_issue_ids
    if missing_research:
        errors.append(f"FACT_GAP issues must appear in research_requests: {sorted(missing_research)}")

    for decision in decisions:
        require_fields(
            decision,
            ("id", "issue_id", "kind", "question", "options", "recommended_option_id"),
            "user_decision.",
            errors,
        )
        issue_id = decision.get("issue_id")
        if issue_id in fact_issue_ids:
            errors.append(f"FACT_GAP {issue_id} must use research_requests, not user_decisions")
        elif issue_id not in issue_ids:
            errors.append(f"user decision references unknown issue: {issue_id}")
        if decision.get("kind") not in USER_DECISION_KINDS:
            errors.append(f"user decision {decision.get('id')} has invalid kind")
        options = decision.get("options")
        if not isinstance(options, list) or len(options) < 2:
            errors.append(f"user decision {decision.get('id')} requires at least two options")
            options = []
        option_ids: set[str] = set()
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                errors.append(f"user decision {decision.get('id')} option {index} must include impact")
                continue
            require_fields(option, ("id", "label", "impact"), "user_decision.option.", errors)
            if option.get("id"):
                option_ids.add(option["id"])
        recommended = decision.get("recommended_option_id")
        if recommended and recommended not in option_ids:
            errors.append(
                f"user decision {decision.get('id')} recommended_option_id must reference an option"
            )

    known_targets = capability_ids | criteria_ids
    trace_targets_by_source: dict[str, set[str]] = {}
    for link in traceability:
        require_fields(link, ("source_ref", "targets"), "traceability.", errors)
        targets = link.get("targets")
        if not isinstance(targets, list) or not targets:
            errors.append("traceability.targets must be a non-empty array")
        elif unknown := set(targets) - known_targets:
            errors.append(f"traceability references unknown targets: {sorted(unknown)}")
        if isinstance(link.get("source_ref"), str) and isinstance(targets, list):
            trace_targets_by_source.setdefault(link["source_ref"], set()).update(targets)

    for item in [*capabilities, *criteria]:
        item_id = item.get("id")
        source_refs = item.get("source_refs")
        if not isinstance(source_refs, list):
            continue
        for source_ref in source_refs:
            if item_id not in trace_targets_by_source.get(source_ref, set()):
                errors.append(f"source_ref {source_ref} must trace to {item_id}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be an object")
    else:
        require_fields(artifacts, ("review", "manifest"), "artifacts.", errors)

    status = manifest.get("status")
    if status == "READY" and (research or decisions or fact_issue_ids):
        errors.append("READY cannot contain unresolved research_requests or user_decisions")
    if status == "NEEDS_RESEARCH" and not research:
        errors.append("NEEDS_RESEARCH requires research_requests")
    if status == "NEEDS_USER_DECISION" and not decisions:
        errors.append("NEEDS_USER_DECISION requires user_decisions")
    if status == "NEEDS_SCOPE_REWORK" and not any(
        item.get("category") == "SCOPE_CONFLICT" for item in issues
    ):
        errors.append("NEEDS_SCOPE_REWORK requires a SCOPE_CONFLICT issue")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-manifest.py <manifest.json|->", file=sys.stderr)
        return 2
    try:
        errors = validate(read_manifest(sys.argv[1]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
