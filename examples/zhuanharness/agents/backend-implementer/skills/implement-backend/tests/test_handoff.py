import copy
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-handoff.py"


def payload() -> dict:
    return {"task_id": "T-2", "role": "backend", "status": "READY_FOR_INTEGRATION", "acceptance_ids": ["AC-2"], "repositories": [{"repository_id": "service", "expected_base_sha": "a" * 40, "output_sha": "b" * 40, "handoff_ref": "refs/zhuanspec/change/handoff/T-2/r1", "changed_paths": ["src/Service.java"], "clean": True, "checks": [{"command": "mvn test", "exit_code": 0, "observed_at": "2026-08-12T10:00:00+08:00", "log_anchor": "git:ref@sha:test.log#sha256=abc"}]}]}


def run(value: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), "-"], input=json.dumps(value), text=True, capture_output=True, check=False)


class HandoffTest(unittest.TestCase):
    def test_valid_backend_handoff(self) -> None:
        self.assertEqual(run(payload()).returncode, 0)

    def test_wrong_role_rejected(self) -> None:
        value = payload()
        value["role"] = "database"
        self.assertIn("frontend or backend", run(value).stderr)

    def test_short_base_rejected(self) -> None:
        value = payload()
        value["repositories"][0]["expected_base_sha"] = "deadbeef"
        self.assertIn("full lowercase", run(value).stderr)

    def test_missing_checks_rejected(self) -> None:
        value = payload()
        value["repositories"][0]["checks"] = []
        self.assertIn("non-empty", run(value).stderr)

    def test_undigested_log_rejected(self) -> None:
        value = copy.deepcopy(payload())
        value["repositories"][0]["checks"][0]["log_anchor"] = "test.log"
        self.assertIn("sha256", run(value).stderr)


if __name__ == "__main__":
    unittest.main()
