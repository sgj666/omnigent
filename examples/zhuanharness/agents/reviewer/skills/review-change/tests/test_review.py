import copy
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-review.py"
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64
AXES = ["SPEC", "STANDARDS", "CORRECTNESS_REGRESSION", "SECURITY_COMPATIBILITY"]


def run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def vector(sha: str = SHA_A) -> dict:
    return {"complete": True, "repositories": [{"repository_id": "orders", "commit_sha": sha}]}


def snapshot(path: str) -> dict:
    return {"ref": "refs/zhuanspec/c/snapshot/r1", "commit_sha": SHA_A, "blob_path": path, "sha256": DIGEST}


def valid_pass() -> dict:
    return {
        "task_id": "R-1", "overall_status": "PASS", "base_vector": vector(SHA_B),
        "tested_vector": vector(), "verified_vector": vector(), "reviewed_vector": vector(), "final_delivery_vector": vector(),
        "artifact_snapshot": snapshot("artifacts/approved.tar"), "standards_snapshot": snapshot("artifacts/standards.tar"),
        "diff_checks": [{"repository_id": "orders", "diff_checked": True, "expected_change": True, "diff_non_empty": True}],
        "axes": [{"axis": axis, "status": "PASS", "summary": "no finding"} for axis in AXES],
        "findings": [], "waivers": [], "read_only": True, "working_tree_used": False,
    }


def finding() -> dict:
    return {"finding_id": "F-001", "severity": "major", "axis": "CORRECTNESS_REGRESSION", "acceptance_id": "AC-001", "repository_id": "orders", "candidate_sha": SHA_A, "path": "src/OrderService.java", "line": 42, "observed_failure": "cancelled order is completed", "evidence": "fixed diff and failed case", "repair_contract": "correct only cancellation transition and rerun TC-004", "kind": "hard_defect", "confidence": "high"}


class ReviewArtifact(unittest.TestCase):
    def test_valid_four_axis_pass(self) -> None:
        self.assertEqual(run(valid_pass()).returncode, 0)

    def test_missing_fixed_base_or_working_tree_review_is_rejected(self) -> None:
        report = valid_pass(); report["base_vector"] = {"complete": False, "repositories": []}; report["working_tree_used"] = True
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base_vector", result.stderr)
        self.assertIn("working tree", result.stderr)

    def test_candidate_vector_mismatch_is_rejected(self) -> None:
        report = valid_pass(); report["verified_vector"] = vector(SHA_B)
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must match", result.stderr)

    def test_all_four_axes_are_required_and_not_averaged(self) -> None:
        report = valid_pass(); report["axes"] = report["axes"][:2]
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly four", result.stderr)

    def test_expected_change_requires_non_empty_fixed_diff(self) -> None:
        report = valid_pass(); report["diff_checks"][0]["diff_non_empty"] = False
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-empty fixed diff", result.stderr)

    def test_finding_requires_location_evidence_and_repair_contract(self) -> None:
        report = valid_pass(); report["overall_status"] = "FAIL"; bad = finding(); bad["line"] = 0; bad["evidence"] = ""; bad["repair_contract"] = ""; report["findings"] = [bad]; report["repair_packet"] = {"modifications_performed": False}
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence is required", result.stderr)
        self.assertIn("repair_contract is required", result.stderr)
        self.assertIn("path:line", result.stderr)

    def test_smell_can_never_be_a_hard_defect(self) -> None:
        report = valid_pass(); report["overall_status"] = "FAIL"; item = finding(); item.update({"axis": "STANDARDS", "source_type": "smell", "kind": "hard_defect"}); report["findings"] = [item]; report["repair_packet"] = {"modifications_performed": False}
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("judgement_call", result.stderr)

    def test_pass_cannot_hide_findings_or_failed_axis(self) -> None:
        report = valid_pass(); item = finding(); item["severity"] = "critical"; report["findings"] = [item]; report["axes"][2]["status"] = "FAIL"
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("critical", result.stderr)
        self.assertIn("failed independent axis", result.stderr)

    def test_pass_can_report_only_minor_judgement_call_without_hiding_it(self) -> None:
        report = valid_pass(); item = finding(); item.update({"severity": "minor", "axis": "STANDARDS", "source_type": "smell", "kind": "judgement_call"}); report["findings"] = [item]; report["axes"][1]["status"] = "PASS_WITH_GAPS"
        self.assertEqual(run(report).returncode, 0)

    def test_axis_verdict_must_match_its_findings(self) -> None:
        report = valid_pass(); report["findings"] = [finding()]
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must FAIL", result.stderr)

    def test_pass_with_gaps_requires_waiver_and_no_failed_axis(self) -> None:
        report = valid_pass(); report["overall_status"] = "PASS_WITH_GAPS"; report["axes"][0]["status"] = "PASS_WITH_GAPS"; report["findings"] = [{**finding(), "severity": "minor", "axis": "SPEC", "kind": "judgement_call"}]
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("waivers", result.stderr)

    def test_fail_requires_minimal_repair_packet_but_no_repair(self) -> None:
        report = valid_pass(); report["overall_status"] = "FAIL"; report["findings"] = [finding()]; report["axes"][2]["status"] = "FAIL"
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("repair_packet", result.stderr)
        report["repair_packet"] = {"modifications_performed": True}
        result = run(report)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not implement", result.stderr)

    def test_skill_does_not_run_tests_or_modify_candidate(self) -> None:
        skill = (ROOT / "SKILL.md").read_text()
        self.assertIn("不运行或补写测试", skill)
        self.assertIn("不修改生产代码", skill)
        self.assertIn("不派生 Reviewer", skill)


if __name__ == "__main__":
    unittest.main()
