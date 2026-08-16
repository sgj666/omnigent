import copy
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-tdd.py"


def payload() -> dict:
    return {
        "task_id": "BE-1",
        "candidate_sha": "a" * 40,
        "policy": {"mode": "required", "source": "proposal", "reason": "bug fix"},
        "cycles": [{
            "acceptance_id": "AC-1",
            "public_seam": "OrderService.cancel",
            "red": {"command": "./test order", "exit_code": 1, "observed_at": "2026-08-12T10:00:00+08:00", "failure_reason": "wrong status", "log_anchor": "git:ref@sha:red.log#sha256=abc"},
            "green": {"command": "./test order", "exit_code": 0, "observed_at": "2026-08-12T10:05:00+08:00", "log_anchor": "git:ref@sha:green.log#sha256=def"},
        }],
    }


def run(value: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), "-"], input=json.dumps(value), text=True, capture_output=True, check=False)


class TddEvidenceTest(unittest.TestCase):
    def test_valid_red_green(self) -> None:
        self.assertEqual(run(payload()).returncode, 0)

    def test_red_cannot_pass(self) -> None:
        value = copy.deepcopy(payload())
        value["cycles"][0]["red"]["exit_code"] = 0
        self.assertIn("non-zero", run(value).stderr)

    def test_compile_error_without_failure_reason_is_rejected(self) -> None:
        value = copy.deepcopy(payload())
        del value["cycles"][0]["red"]["failure_reason"]
        self.assertIn("failure_reason", run(value).stderr)

    def test_required_policy_needs_cycle(self) -> None:
        value = payload()
        value["cycles"] = []
        self.assertIn("RED/GREEN", run(value).stderr)

    def test_temporary_log_path_is_rejected(self) -> None:
        value = copy.deepcopy(payload())
        value["cycles"][0]["green"]["log_anchor"] = "/tmp/green.log"
        self.assertIn("persistent", run(value).stderr)


if __name__ == "__main__":
    unittest.main()
