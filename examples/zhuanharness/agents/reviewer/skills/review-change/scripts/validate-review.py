#!/usr/bin/env python3
"""Validate a zhuanharness independent review artifact."""

import json
import re
import sys
from pathlib import Path
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
AXES = {"SPEC", "STANDARDS", "CORRECTNESS_REGRESSION", "SECURITY_COMPATIBILITY"}
AXIS_STATUSES = {"PASS", "PASS_WITH_GAPS", "FAIL"}
OVERALL = {"PASS", "PASS_WITH_GAPS", "FAIL"}
SEVERITIES = {"blocker", "critical", "major", "minor"}
KINDS = {"hard_defect", "judgement_call"}
CONFIDENCE = {"high", "medium", "low"}


def read_json(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("review artifact must be a JSON object")
    return value


def required(obj: dict[str, Any], fields: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for field in fields:
        if field not in obj or obj[field] in (None, "", []):
            errors.append(f"{prefix}{field} is required")


def vector(value: Any, name: str, errors: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return {}
    if value.get("complete") is not True:
        errors.append(f"{name} must be COMPLETE")
    repos = value.get("repositories")
    if not isinstance(repos, list) or not repos:
        errors.append(f"{name}.repositories must be non-empty")
        return {}
    result: dict[str, str] = {}
    for repo in repos:
        if not isinstance(repo, dict):
            errors.append(f"{name} repository must be an object")
            continue
        required(repo, ("repository_id", "commit_sha"), f"{name}.repository.", errors)
        repo_id, commit = repo.get("repository_id"), repo.get("commit_sha")
        if repo_id in result:
            errors.append(f"duplicate repository_id in {name}: {repo_id}")
        if not isinstance(commit, str) or not SHA.fullmatch(commit):
            errors.append(f"{name} commit_sha must be a full 40-character SHA")
        if isinstance(repo_id, str) and isinstance(commit, str):
            result[repo_id] = commit
    return result


def snapshot(value: Any, name: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return
    required(value, ("ref", "commit_sha", "blob_path", "sha256"), f"{name}.", errors)
    if not isinstance(value.get("ref"), str) or not value["ref"].startswith("refs/"):
        errors.append(f"{name}.ref must be immutable")
    if not isinstance(value.get("commit_sha"), str) or not SHA.fullmatch(value["commit_sha"]):
        errors.append(f"{name}.commit_sha must be a full 40-character SHA")
    if not isinstance(value.get("sha256"), str) or not DIGEST.fullmatch(value["sha256"]):
        errors.append(f"{name}.sha256 must be a 64-character digest")


def validate(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required(report, ("task_id", "overall_status", "base_vector", "tested_vector", "verified_vector", "reviewed_vector", "final_delivery_vector", "artifact_snapshot", "standards_snapshot", "diff_checks", "axes", "read_only", "working_tree_used"), "", errors)
    overall = report.get("overall_status")
    if overall not in OVERALL:
        errors.append("overall_status is invalid")
    if report.get("read_only") is not True:
        errors.append("Reviewer must remain read-only")
    if report.get("working_tree_used") is not False:
        errors.append("Reviewer must inspect fixed Git objects, not the working tree")
    base = vector(report.get("base_vector"), "base_vector", errors)
    tested = vector(report.get("tested_vector"), "tested_vector", errors)
    verified = vector(report.get("verified_vector"), "verified_vector", errors)
    reviewed = vector(report.get("reviewed_vector"), "reviewed_vector", errors)
    final = vector(report.get("final_delivery_vector"), "final_delivery_vector", errors)
    if not base:
        errors.append("a fixed base_vector is required")
    vectors_equal = tested == verified == reviewed == final and bool(final)
    if not vectors_equal:
        errors.append("tested_vector, verified_vector, reviewed_vector and final_delivery_vector must match")
    snapshot(report.get("artifact_snapshot"), "artifact_snapshot", errors)
    snapshot(report.get("standards_snapshot"), "standards_snapshot", errors)

    diff_checks = report.get("diff_checks")
    if not isinstance(diff_checks, list) or not diff_checks:
        errors.append("diff_checks must be a non-empty array")
        diff_checks = []
    checked_repos: set[str] = set()
    for check in diff_checks:
        if not isinstance(check, dict):
            errors.append("diff check must be an object")
            continue
        required(check, ("repository_id", "diff_checked", "expected_change", "diff_non_empty"), "diff_check.", errors)
        checked_repos.add(check.get("repository_id"))
        if check.get("diff_checked") is not True:
            errors.append(f"repository {check.get('repository_id')} fixed diff must be checked")
        if check.get("expected_change") is True and check.get("diff_non_empty") is not True:
            errors.append(f"repository {check.get('repository_id')} expected change requires a non-empty fixed diff")
    if checked_repos != set(final):
        errors.append("diff_checks must cover every reviewed repository")

    axes = report.get("axes")
    if not isinstance(axes, list) or len(axes) != 4:
        errors.append("axes must contain exactly four independent axis verdicts")
        axes = []
    axis_names: set[str] = set()
    for axis in axes:
        if not isinstance(axis, dict):
            errors.append("axis verdict must be an object")
            continue
        required(axis, ("axis", "status", "summary"), "axis.", errors)
        if axis.get("axis") not in AXES:
            errors.append(f"invalid axis: {axis.get('axis')}")
        axis_names.add(axis.get("axis"))
        if axis.get("status") not in AXIS_STATUSES:
            errors.append(f"axis {axis.get('axis')} has invalid status")
    if axis_names != AXES:
        errors.append("all four review axes must be reported separately")

    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
        findings = []
    finding_ids: set[str] = set()
    candidate_shas = set(final.values())
    for finding in findings:
        if not isinstance(finding, dict):
            errors.append("finding must be an object")
            continue
        required(finding, ("finding_id", "severity", "axis", "repository_id", "candidate_sha", "path", "line", "observed_failure", "evidence", "repair_contract", "kind", "confidence"), "finding.", errors)
        finding_id = finding.get("finding_id")
        if finding_id in finding_ids:
            errors.append(f"duplicate finding_id: {finding_id}")
        finding_ids.add(finding_id)
        if finding.get("severity") not in SEVERITIES:
            errors.append(f"finding {finding_id} has invalid severity")
        if finding.get("axis") not in AXES:
            errors.append(f"finding {finding_id} has invalid axis")
        if finding.get("kind") not in KINDS:
            errors.append(f"finding {finding_id} has invalid kind")
        if finding.get("confidence") not in CONFIDENCE:
            errors.append(f"finding {finding_id} has invalid confidence")
        if finding.get("candidate_sha") not in candidate_shas:
            errors.append(f"finding {finding_id} must reference the reviewed candidate SHA")
        if not isinstance(finding.get("line"), int) or finding["line"] < 1:
            errors.append(f"finding {finding_id} requires a positive path:line")
        if finding.get("axis") == "STANDARDS" and finding.get("source_type") == "smell" and finding.get("kind") != "judgement_call":
            errors.append(f"standards smell {finding_id} must remain a judgement_call")

    findings_by_axis: dict[str, list[dict[str, Any]]] = {axis: [] for axis in AXES}
    for finding in findings:
        if isinstance(finding, dict) and finding.get("axis") in AXES:
            findings_by_axis[finding["axis"]].append(finding)
    for axis in axes:
        if not isinstance(axis, dict) or axis.get("axis") not in AXES:
            continue
        axis_findings = findings_by_axis[axis["axis"]]
        axis_blocking = [
            item for item in axis_findings
            if item.get("kind") == "hard_defect" or item.get("severity") in {"blocker", "critical", "major"}
        ]
        if axis_findings and axis.get("status") == "PASS":
            errors.append(f"axis {axis['axis']} with findings must not report PASS")
        if axis_blocking and axis.get("status") != "FAIL":
            errors.append(f"axis {axis['axis']} with hard/major findings must FAIL")
        if not axis_findings and axis.get("status") != "PASS":
            errors.append(f"axis {axis['axis']} without findings must PASS")

    blocking = [item for item in findings if isinstance(item, dict) and item.get("severity") in {"blocker", "critical"}]
    delivery_blocking = [item for item in findings if isinstance(item, dict) and (item.get("kind") == "hard_defect" or item.get("severity") in {"blocker", "critical", "major"})]
    failed_axes = [axis for axis in axes if isinstance(axis, dict) and axis.get("status") == "FAIL"]
    if overall == "PASS":
        if blocking:
            errors.append("PASS cannot contain blocker or critical findings")
        if delivery_blocking:
            errors.append("PASS cannot contain hard defects or major findings")
        if any(isinstance(axis, dict) and axis.get("status") == "FAIL" for axis in axes):
            errors.append("PASS cannot contain a failed independent axis")
        if not vectors_equal:
            errors.append("PASS requires identical tested/verified/reviewed/delivery vectors")
    if overall == "PASS_WITH_GAPS":
        waivers = report.get("waivers")
        if not isinstance(waivers, list) or not any(
            isinstance(item, dict) and item.get("approved") is True and item.get("waiver_id")
            for item in waivers
        ):
            errors.append("PASS_WITH_GAPS requires approved waivers")
        if delivery_blocking or failed_axes:
            errors.append("PASS_WITH_GAPS cannot hide hard/major findings or failed axes")
    if overall == "FAIL":
        repair = report.get("repair_packet")
        if not findings or not isinstance(repair, dict):
            errors.append("FAIL requires findings and a minimal repair_packet")
        elif repair.get("modifications_performed") is not False:
            errors.append("Reviewer must not implement the repair_packet")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-review.py <findings.json|->", file=sys.stderr)
        return 2
    try:
        errors = validate(read_json(sys.argv[1]))
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
