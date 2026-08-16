import copy
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-test-artifact.py"
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64


def run(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), kind, "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def vector(sha: str = SHA_A) -> dict:
    return {"complete": True, "repositories": [{"repository_id": "orders", "commit_sha": sha}]}


def case(status: str | None = None) -> dict:
    value = {
        "case_id": "TC-001", "acceptance_id": "AC-001", "risk": "boundary",
        "seam": "public API: OrderQuery.query", "setup": "two states", "action": "query completed",
        "assertion": "only completed orders", "independent_expected": True, "layer": "api", "blocking": True,
    }
    if status:
        value.update({"status": status, "execution": {"command": "./mvnw test", "exit_code": 0, "started_at": "2026-08-12T10:00:00Z", "finished_at": "2026-08-12T10:01:00Z", "evidence": {"repository_id": "control", "ref": "refs/zhuanspec/c/evidence/test/r1", "commit_sha": SHA_A, "blob_path": "evidence/test.log", "sha256": DIGEST}}})
    return value


class TestArtifacts(unittest.TestCase):
    def test_valid_risk_driven_plan(self) -> None:
        payload = {"task_id": "T-1", "mode": "verify", "acceptance_ids": ["AC-001"], "blocking_acceptance_ids": ["AC-001"], "candidate_vector": vector(), "cases": [case()]}
        self.assertEqual(run("plan", payload).returncode, 0)

    def test_every_acceptance_needs_a_blocking_case(self) -> None:
        payload = {"task_id": "T-1", "mode": "verify", "acceptance_ids": ["AC-001", "AC-002"], "blocking_acceptance_ids": ["AC-001", "AC-002"], "candidate_vector": vector(), "cases": [case()]}
        result = run("plan", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("blocking case", result.stderr)

    def test_private_seam_and_implementation_derived_expectation_are_rejected(self) -> None:
        bad = case(); bad["seam"] = "private method"; bad["independent_expected"] = False
        payload = {"task_id": "T-1", "mode": "verify", "acceptance_ids": ["AC-001"], "blocking_acceptance_ids": ["AC-001"], "candidate_vector": vector(), "cases": [bad]}
        result = run("plan", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("public seam", result.stderr)
        self.assertIn("independent expected", result.stderr)

    def test_author_mode_can_only_return_tests_authored(self) -> None:
        payload = {"task_id": "T-1", "status": "TEST_PASS", "production_files_modified": False, "repositories": [{"repository_id": "orders", "commit_sha": SHA_A, "test_ref": "refs/zhuanspec/c/tests/t/r1", "files": ["src/test/Test.java"], "sha256": DIGEST}]}
        result = run("handoff", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TESTS_AUTHORED", result.stderr)

    def test_author_mode_rejects_production_edits(self) -> None:
        payload = {"task_id": "T-1", "status": "TESTS_AUTHORED", "production_files_modified": True, "repositories": [{"repository_id": "orders", "commit_sha": SHA_A, "test_ref": "refs/zhuanspec/c/tests/t/r1", "files": ["src/test/Test.java"], "sha256": DIGEST}]}
        self.assertNotEqual(run("handoff", payload).returncode, 0)

    def test_valid_verify_result_is_accepted(self) -> None:
        payload = {"task_id": "T-1", "status": "TEST_PASS", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [case("PASS")], "production_files_modified": False}
        self.assertEqual(run("result", payload).returncode, 0)

    def test_honest_blocked_result_does_not_require_fake_execution(self) -> None:
        blocked = case(); blocked.update({"status": "BLOCKED", "reason": "browser runner is unavailable"})
        payload = {"task_id": "T-1", "status": "TEST_BLOCKED", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [blocked], "production_files_modified": False}
        self.assertEqual(run("result", payload).returncode, 0)

    def test_stale_candidate_is_rejected(self) -> None:
        payload = {"task_id": "T-1", "status": "TEST_PASS", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(SHA_B), "cases": [case("PASS")], "production_files_modified": False}
        result = run("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tested_vector", result.stderr)

    def test_blocked_webui_cannot_be_test_pass(self) -> None:
        blocked = case("BLOCKED"); blocked["layer"] = "webui"; blocked["execution"]["exit_code"] = 2
        payload = {"task_id": "T-1", "status": "TEST_PASS", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [blocked], "production_files_modified": False}
        result = run("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must PASS", result.stderr)

    def test_pass_case_requires_zero_exit_code(self) -> None:
        failed_command = case("PASS"); failed_command["execution"]["exit_code"] = 1
        payload = {"task_id": "T-1", "status": "TEST_PASS", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [failed_command], "production_files_modified": False}
        result = run("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-zero", result.stderr)

    def test_blocking_skip_requires_explicit_approved_waiver(self) -> None:
        skipped = case(); skipped.update({"status": "SKIPPED", "reason": "environment unavailable"})
        payload = {"task_id": "T-1", "status": "TEST_SKIPPED", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [skipped], "production_files_modified": False, "waiver": {"waiver_id": "W-1", "approved": False}}
        result = run("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved waiver", result.stderr)

    def test_attempt_absolute_evidence_is_rejected(self) -> None:
        bad = case("PASS"); bad["execution"]["evidence"]["blob_path"] = "/runtime/attempt-1/test.log"
        payload = {"task_id": "T-1", "status": "TEST_PASS", "acceptance_ids": ["AC-001"], "tested_vector": vector(), "final_candidate_vector": vector(), "cases": [bad], "production_files_modified": False}
        result = run("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Attempt absolute", result.stderr)

    def test_skill_keeps_tdd_and_review_outside_test_engineer(self) -> None:
        text = (ROOT / "SKILL.md").read_text()
        self.assertIn("TDD 的 RED-GREEN 循环属于 Frontend/Backend Implementer", text)
        self.assertIn("不用于修改生产代码", text)
        self.assertIn("不用于", text)


if __name__ == "__main__":
    unittest.main()
