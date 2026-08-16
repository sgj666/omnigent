#!/usr/bin/env python3
"""Validate a zhuanharness delivery verification report."""

import json
import re
import sys
from pathlib import Path
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
STATUSES = {"VERIFIED", "VERIFICATION_FAILED", "VERIFICATION_BLOCKED"}
GATE_STATUSES = {"PASS", "FAIL", "BLOCKED", "SKIPPED"}
PROOF_TYPES = {"lint", "build", "test", "acceptance", "artifact-integrity"}


def read_json(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("verification report must be a JSON object")
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


def anchor(value: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    required(value, ("repository_id", "ref", "commit_sha", "blob_path", "sha256", "resolvable"), prefix, errors)
    if not isinstance(value.get("commit_sha"), str) or not SHA.fullmatch(value["commit_sha"]):
        errors.append(f"{prefix}commit_sha must be a full 40-character SHA")
    if not isinstance(value.get("sha256"), str) or not DIGEST.fullmatch(value["sha256"]):
        errors.append(f"{prefix}sha256 must be a 64-character digest")
    if not isinstance(value.get("ref"), str) or not value["ref"].startswith("refs/"):
        errors.append(f"{prefix}ref must be immutable and start with refs/")
    if value.get("resolvable") is not True:
        errors.append(f"{prefix}must be resolvable")
    blob = value.get("blob_path")
    if isinstance(blob, str) and (blob.startswith("/") or "/attempt" in blob):
        errors.append(f"{prefix}blob_path must be durable, not an Attempt path")


def validate(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required(report, ("task_id", "status", "artifact_snapshot", "tested_vector", "verified_vector", "final_candidate_vector", "gates", "acceptance_results", "read_only"), "", errors)
    status = report.get("status")
    if status not in STATUSES:
        errors.append("status is invalid")
    if report.get("read_only") is not True:
        errors.append("Verifier must remain read-only")
    snapshot = report.get("artifact_snapshot")
    anchor(snapshot, "artifact_snapshot.", errors)
    tested = vector(report.get("tested_vector"), "tested_vector", errors)
    verified = vector(report.get("verified_vector"), "verified_vector", errors)
    final = vector(report.get("final_candidate_vector"), "final_candidate_vector", errors)
    vectors_equal = tested == verified == final and bool(final)
    if not vectors_equal:
        errors.append("tested_vector must equal verified_vector and final_candidate_vector")

    gates = report.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates must be a non-empty array")
        gates = []
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            errors.append(f"gates[{index}] must be an object")
            continue
        required(gate, ("gate_id", "kind", "required", "status"), "gate.", errors)
        gate_status = gate.get("status")
        if gate_status not in GATE_STATUSES:
            errors.append(f"gate {gate.get('gate_id')} has invalid status")
        execution = gate.get("execution")
        if gate_status in {"BLOCKED", "SKIPPED"}:
            if not gate.get("reason"):
                errors.append(f"gate {gate.get('gate_id')} BLOCKED/SKIPPED requires a reason")
            continue
        if not isinstance(execution, dict):
            errors.append(f"gate {gate.get('gate_id')} PASS/FAIL requires an execution object")
            continue
        required(execution, ("command", "proof_type", "exit_code", "started_at", "finished_at", "candidate_digest", "evidence"), "execution.", errors)
        proof_type = execution.get("proof_type")
        if proof_type not in PROOF_TYPES:
            errors.append(f"gate {gate.get('gate_id')} has invalid proof_type")
        if gate.get("kind") == "build" and proof_type != "build":
            errors.append("a build gate requires build proof; lint is insufficient")
        if gate.get("kind") == "acceptance" and proof_type != "acceptance":
            errors.append("an acceptance gate requires acceptance proof")
        if gate_status == "PASS" and execution.get("exit_code") != 0:
            errors.append(f"gate {gate.get('gate_id')} cannot PASS with non-zero exit_code")
        if not isinstance(execution.get("candidate_digest"), str) or not DIGEST.fullmatch(execution["candidate_digest"]):
            errors.append("execution.candidate_digest must be a 64-character digest")
        anchor(execution.get("evidence"), "execution.evidence.", errors)

    acceptance_results = report.get("acceptance_results")
    if not isinstance(acceptance_results, list) or not acceptance_results:
        errors.append("acceptance_results must be a non-empty array")
        acceptance_results = []
    waiver_ids = {
        item.get("waiver_id")
        for item in report.get("waivers", [])
        if isinstance(item, dict) and item.get("approved") is True
    }
    for item in acceptance_results:
        if not isinstance(item, dict):
            errors.append("acceptance result must be an object")
            continue
        required(item, ("acceptance_id", "blocking", "status", "case_ids"), "acceptance.", errors)
        acceptance_status = item.get("status")
        if acceptance_status not in {"PASS", "FAIL", "BLOCKED", "SKIPPED"}:
            errors.append(f"acceptance {item.get('acceptance_id')} has invalid status")
        evidence = item.get("evidence")
        if acceptance_status in {"PASS", "FAIL"} and (not isinstance(evidence, list) or not evidence):
            errors.append(f"acceptance {item.get('acceptance_id')} requires behavioral evidence")
        elif isinstance(evidence, list):
            for value in evidence:
                anchor(value, "acceptance.evidence.", errors)
        if acceptance_status in {"BLOCKED", "SKIPPED"} and not item.get("reason"):
            errors.append(f"acceptance {item.get('acceptance_id')} BLOCKED/SKIPPED requires a reason")
        if item.get("blocking") is True and acceptance_status == "SKIPPED" and item.get("waiver_id") not in waiver_ids:
            errors.append(f"blocking acceptance {item.get('acceptance_id')} needs an approved waiver")

    if status == "VERIFIED":
        if not vectors_equal:
            errors.append("VERIFIED requires identical candidate vectors")
        for gate in gates:
            if isinstance(gate, dict) and gate.get("required") is True and gate.get("status") != "PASS":
                errors.append(f"required gate {gate.get('gate_id')} must PASS before VERIFIED")
        for item in acceptance_results:
            if isinstance(item, dict) and item.get("blocking") is True and item.get("status") != "PASS":
                errors.append(f"blocking acceptance {item.get('acceptance_id')} must PASS before VERIFIED")
    if status == "VERIFICATION_FAILED" and not (
        any(isinstance(gate, dict) and gate.get("status") == "FAIL" for gate in gates)
        or any(isinstance(item, dict) and item.get("status") == "FAIL" for item in acceptance_results)
        or not vectors_equal
    ):
        errors.append("VERIFICATION_FAILED requires a failed gate, failed acceptance, or vector mismatch")
    if status == "VERIFICATION_BLOCKED" and not (
        any(isinstance(gate, dict) and gate.get("status") == "BLOCKED" for gate in gates)
        or any(isinstance(item, dict) and item.get("status") == "BLOCKED" for item in acceptance_results)
    ):
        errors.append("VERIFICATION_BLOCKED requires a blocked gate or acceptance")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate-verification.py <verification-report.json|->", file=sys.stderr)
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
