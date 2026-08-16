#!/usr/bin/env python3
"""Validate zhuanharness test plans, authored-test handoffs, and test results."""

import json
import re
import sys
from pathlib import Path
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
RISKS = {"normal", "boundary", "error", "permission", "compatibility", "regression"}
LAYERS = {"unit", "component", "api", "integration", "webui"}


def read_json(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("artifact must be a JSON object")
    return value


def required(obj: dict[str, Any], fields: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for field in fields:
        if field not in obj or obj[field] in (None, "", []):
            errors.append(f"{prefix}{field} is required")


def validate_vector(value: Any, name: str, errors: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return {}
    if value.get("complete") is not True:
        errors.append(f"{name} must be COMPLETE")
    repos = value.get("repositories")
    if not isinstance(repos, list) or not repos:
        errors.append(f"{name}.repositories must be a non-empty array")
        return {}
    result: dict[str, str] = {}
    for index, repo in enumerate(repos):
        if not isinstance(repo, dict):
            errors.append(f"{name}.repositories[{index}] must be an object")
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


def validate_anchor(anchor: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(anchor, dict):
        errors.append(f"{prefix} must be an object")
        return
    required(anchor, ("repository_id", "ref", "commit_sha", "blob_path", "sha256"), prefix, errors)
    if not isinstance(anchor.get("commit_sha"), str) or not SHA.fullmatch(anchor["commit_sha"]):
        errors.append(f"{prefix}commit_sha must be a full 40-character SHA")
    if not isinstance(anchor.get("sha256"), str) or not DIGEST.fullmatch(anchor["sha256"]):
        errors.append(f"{prefix}sha256 must be a 64-character digest")
    ref = anchor.get("ref")
    if not isinstance(ref, str) or not ref.startswith("refs/zhuanspec/"):
        errors.append(f"{prefix}ref must be an immutable refs/zhuanspec ref")
    blob_path = anchor.get("blob_path")
    if isinstance(blob_path, str) and (blob_path.startswith("/") or "/attempt" in blob_path):
        errors.append(f"{prefix}blob_path must not be an Attempt absolute path")


def validate_cases(cases: Any, acceptance_ids: set[str], errors: list[str], result_mode: bool = False) -> list[dict[str, Any]]:
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty array")
        return []
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{index}] must be an object")
            continue
        required(case, ("case_id", "acceptance_id", "risk", "seam", "setup", "action", "assertion", "layer", "blocking"), "case.", errors)
        case_id = case.get("case_id")
        if case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        if case.get("acceptance_id") not in acceptance_ids:
            errors.append(f"case {case_id} references unknown acceptance_id")
        if case.get("risk") not in RISKS:
            errors.append(f"case {case_id} has invalid risk")
        if case.get("layer") not in LAYERS:
            errors.append(f"case {case_id} has invalid layer")
        if case.get("independent_expected") is not True:
            errors.append(f"case {case_id} must use an independent expected result")
        seam = str(case.get("seam", "")).lower()
        if "private" in seam or "internal method" in seam:
            errors.append(f"case {case_id} must test a public seam")
        if result_mode:
            required(case, ("status",), "case.", errors)
            status = case.get("status")
            if status not in {"PASS", "FAIL", "BLOCKED", "SKIPPED"}:
                errors.append(f"case {case_id} has invalid status")
            execution = case.get("execution")
            if status in {"PASS", "FAIL"} and not isinstance(execution, dict):
                errors.append(f"case {case_id} PASS/FAIL requires an execution object")
            elif isinstance(execution, dict):
                required(execution, ("command", "exit_code", "started_at", "finished_at", "evidence"), "execution.", errors)
                validate_anchor(execution.get("evidence"), "execution.evidence.", errors)
                if status == "PASS" and execution.get("exit_code") != 0:
                    errors.append(f"case {case_id} cannot PASS with non-zero exit_code")
            if status in {"BLOCKED", "SKIPPED"} and not case.get("reason"):
                errors.append(f"case {case_id} BLOCKED/SKIPPED requires a reason")
        output.append(case)
    return output


def validate_plan(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required(value, ("task_id", "mode", "acceptance_ids", "blocking_acceptance_ids", "candidate_vector", "cases"), "", errors)
    if value.get("mode") not in {"author", "verify"}:
        errors.append("mode must be author or verify")
    ids = value.get("acceptance_ids")
    acceptance_ids = set(ids) if isinstance(ids, list) else set()
    if not acceptance_ids:
        errors.append("acceptance_ids must be a non-empty array")
    blocking_ids = value.get("blocking_acceptance_ids")
    blocking_acceptance_ids = set(blocking_ids) if isinstance(blocking_ids, list) else set()
    if not blocking_acceptance_ids.issubset(acceptance_ids):
        errors.append("blocking_acceptance_ids must be a subset of acceptance_ids")
    validate_vector(value.get("candidate_vector"), "candidate_vector", errors)
    cases = validate_cases(value.get("cases"), acceptance_ids, errors)
    covered = {case.get("acceptance_id") for case in cases}
    if missing := acceptance_ids - covered:
        errors.append(f"every acceptance requires a case: {sorted(missing)}")
    blocking_covered = {case.get("acceptance_id") for case in cases if case.get("blocking") is True}
    if missing := blocking_acceptance_ids - blocking_covered:
        errors.append(f"every blocking acceptance requires a blocking case: {sorted(missing)}")
    return errors


def validate_handoff(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required(value, ("task_id", "status", "production_files_modified", "repositories"), "", errors)
    if value.get("status") != "TESTS_AUTHORED":
        errors.append("author mode status must be TESTS_AUTHORED, never PASS")
    if value.get("production_files_modified") is not False:
        errors.append("author mode must not modify production files")
    repos = value.get("repositories")
    if not isinstance(repos, list) or not repos:
        errors.append("repositories must be a non-empty array")
        return errors
    for repo in repos:
        if not isinstance(repo, dict):
            errors.append("repository handoff must be an object")
            continue
        required(repo, ("repository_id", "commit_sha", "test_ref", "files", "sha256"), "repository.", errors)
        if not isinstance(repo.get("commit_sha"), str) or not SHA.fullmatch(repo["commit_sha"]):
            errors.append("repository.commit_sha must be a full 40-character SHA")
        ref = repo.get("test_ref")
        if not isinstance(ref, str) or not ref.startswith("refs/zhuanspec/"):
            errors.append("repository.test_ref must be an immutable refs/zhuanspec ref")
        if not isinstance(repo.get("sha256"), str) or not DIGEST.fullmatch(repo["sha256"]):
            errors.append("repository.sha256 must be a 64-character digest")
    return errors


def validate_result(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required(value, ("task_id", "status", "acceptance_ids", "tested_vector", "final_candidate_vector", "cases", "production_files_modified"), "", errors)
    status = value.get("status")
    if status not in {"TEST_PASS", "TEST_FAIL", "TEST_BLOCKED", "TEST_SKIPPED"}:
        errors.append("status is invalid")
    if value.get("production_files_modified") is not False:
        errors.append("verify mode must not modify production files")
    tested = validate_vector(value.get("tested_vector"), "tested_vector", errors)
    final = validate_vector(value.get("final_candidate_vector"), "final_candidate_vector", errors)
    if tested != final:
        errors.append("tested_vector must equal final_candidate_vector")
    ids = value.get("acceptance_ids")
    acceptance_ids = set(ids) if isinstance(ids, list) else set()
    cases = validate_cases(value.get("cases"), acceptance_ids, errors, result_mode=True)
    if status == "TEST_PASS":
        for case in cases:
            if case.get("blocking") is True and case.get("status") != "PASS":
                errors.append(f"blocking case {case.get('case_id')} must PASS before TEST_PASS")
    if status == "TEST_FAIL" and not any(case.get("status") == "FAIL" for case in cases):
        errors.append("TEST_FAIL requires at least one failed case")
    if status == "TEST_BLOCKED" and not any(case.get("status") == "BLOCKED" for case in cases):
        errors.append("TEST_BLOCKED requires at least one blocked case")
    if status == "TEST_SKIPPED":
        waiver = value.get("waiver")
        if any(case.get("blocking") is True for case in cases) and not (
            isinstance(waiver, dict) and waiver.get("approved") is True and waiver.get("waiver_id")
        ):
            errors.append("skipping a blocking case requires an approved waiver")
    return errors


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"plan", "handoff", "result"}:
        print("usage: validate-test-artifact.py plan|handoff|result <json|->", file=sys.stderr)
        return 2
    try:
        value = read_json(sys.argv[2])
        errors = {"plan": validate_plan, "handoff": validate_handoff, "result": validate_result}[sys.argv[1]](value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "kind": sys.argv[1]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
