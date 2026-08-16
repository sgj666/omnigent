import copy
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-handoff.py"


def payload(role: str = "frontend") -> dict:
    return {"task_id": "T-1", "role": role, "status": "READY_FOR_INTEGRATION", "acceptance_ids": ["AC-1"], "repositories": [{"repository_id": "web", "expected_base_sha": "a" * 40, "output_sha": "b" * 40, "handoff_ref": "refs/zhuanspec/change/handoff/T-1/r1", "changed_paths": ["src/page.tsx"], "clean": True, "checks": [{"command": "npm test", "exit_code": 0, "observed_at": "2026-08-12T10:00:00+08:00", "log_anchor": "git:ref@sha:test.log#sha256=abc"}]}]}


def run(value: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), "-"], input=json.dumps(value), text=True, capture_output=True, check=False)


class HandoffTest(unittest.TestCase):
    def test_valid_handoff(self) -> None:
        self.assertEqual(run(payload()).returncode, 0)

    def test_short_sha_rejected(self) -> None:
        value = payload()
        value["repositories"][0]["output_sha"] = "abc123"
        self.assertIn("full lowercase", run(value).stderr)

    def test_mutable_ref_rejected(self) -> None:
        value = payload()
        value["repositories"][0]["handoff_ref"] = "refs/heads/task"
        self.assertIn("semantic", run(value).stderr)

    def test_dirty_output_rejected(self) -> None:
        value = payload()
        value["repositories"][0]["clean"] = False
        self.assertIn("clean", run(value).stderr)

    def test_failed_check_rejected(self) -> None:
        value = copy.deepcopy(payload())
        value["repositories"][0]["checks"][0]["exit_code"] = 1
        self.assertIn("must pass", run(value).stderr)


if __name__ == "__main__":
    unittest.main()
