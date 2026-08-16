import copy
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-verification.py"
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64


def run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def vector(sha: str = SHA_A) -> dict:
    return {"complete": True, "repositories": [{"repository_id": "orders", "commit_sha": sha}]}


def anchor(path: str = "evidence/output.log") -> dict:
    return {"repository_id": "control", "ref": "refs/zhuanspec/c/evidence/verify/r1", "commit_sha": SHA_A, "blob_path": path, "sha256": DIGEST, "resolvable": True}


def valid_report() -> dict:
    return {
        "task_id": "V-1", "status": "VERIFIED", "artifact_snapshot": anchor("artifacts/snapshot.tar"),
        "tested_vector": vector(), "verified_vector": vector(), "final_candidate_vector": vector(),
        "gates": [{"gate_id": "G-BUILD", "kind": "build", "required": True, "status": "PASS", "execution": {"command": "./mvnw package", "proof_type": "build", "exit_code": 0, "started_at": "2026-08-12T10:00:00Z", "finished_at": "2026-08-12T10:01:00Z", "candidate_digest": DIGEST, "evidence": anchor()}}],
        "acceptance_results": [{"acceptance_id": "AC-001", "blocking": True, "status": "PASS", "case_ids": ["TC-001"], "evidence": [anchor("evidence/tc-001.log")]}],
        "waivers": [], "read_only": True,
    }


class VerificationReport(unittest.TestCase):
    def test_valid_fresh_evidence_report(self) -> None:
        self.assertEqual(run(valid_report()).returncode, 0)

    def test_incomplete_or_short_sha_vector_is_rejected(self) -> None:
        report = valid_report(); report["verified_vector"] = {"complete": False, "repositories": [{"repository_id": "orders", "commit_sha": "abc123"}]}
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("COMPLETE", result.stderr)
        self.assertIn("40-character", result.stderr)

    def test_stale_tested_vector_is_rejected(self) -> None:
        report = valid_report(); report["tested_vector"] = vector(SHA_B)
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tested_vector", result.stderr)

    def test_non_resolvable_or_attempt_evidence_is_rejected(self) -> None:
        report = valid_report(); report["gates"][0]["execution"]["evidence"] = anchor("/runtime/attempt-1/build.log"); report["gates"][0]["execution"]["evidence"]["resolvable"] = False
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resolvable", result.stderr)
        self.assertIn("Attempt path", result.stderr)

    def test_worker_done_without_acceptance_evidence_is_rejected(self) -> None:
        report = valid_report(); report["acceptance_results"][0]["evidence"] = []
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("behavioral evidence", result.stderr)

    def test_lint_cannot_prove_build(self) -> None:
        report = valid_report(); report["gates"][0]["execution"]["command"] = "npm run lint"; report["gates"][0]["execution"]["proof_type"] = "lint"
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lint is insufficient", result.stderr)

    def test_non_zero_command_cannot_pass(self) -> None:
        report = valid_report(); report["gates"][0]["execution"]["exit_code"] = 1
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-zero", result.stderr)

    def test_required_gate_or_blocking_acceptance_cannot_be_skipped(self) -> None:
        report = valid_report(); report["gates"][0]["status"] = "SKIPPED"; report["gates"][0]["reason"] = "runner unavailable"; report["gates"][0].pop("execution"); report["acceptance_results"][0].update({"status": "BLOCKED", "reason": "runner unavailable"})
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required gate", result.stderr)
        self.assertIn("blocking acceptance", result.stderr)

    def test_honest_blocked_gate_does_not_require_fake_execution(self) -> None:
        report = valid_report(); report["status"] = "VERIFICATION_BLOCKED"; report["gates"][0] = {"gate_id": "G-BUILD", "kind": "build", "required": True, "status": "BLOCKED", "reason": "build runner is unavailable"}; report["acceptance_results"][0] = {"acceptance_id": "AC-001", "blocking": True, "status": "BLOCKED", "case_ids": ["TC-001"], "reason": "browser unavailable"}
        self.assertEqual(run(report).returncode, 0)

    def test_blocking_acceptance_skip_requires_approved_waiver(self) -> None:
        report = valid_report(); report["status"] = "VERIFICATION_BLOCKED"; report["gates"][0] = {"gate_id": "G-BUILD", "kind": "build", "required": True, "status": "BLOCKED", "reason": "runner unavailable"}; report["acceptance_results"][0] = {"acceptance_id": "AC-001", "blocking": True, "status": "SKIPPED", "case_ids": ["TC-001"], "reason": "waived", "waiver_id": "W-1"}; report["waivers"] = [{"waiver_id": "W-1", "approved": False}]
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved waiver", result.stderr)

    def test_verifier_is_read_only_and_not_reviewer(self) -> None:
        report = valid_report(); report["read_only"] = False
        self.assertNotEqual(run(report).returncode, 0)
        skill = (ROOT / "SKILL.md").read_text()
        self.assertIn("不是 Reviewer", skill)
        self.assertIn("不审查代码风格", skill)


if __name__ == "__main__":
    unittest.main()
