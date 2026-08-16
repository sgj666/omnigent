import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-proposal.py"


def validate(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), kind, "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def valid_output() -> dict:
    return {"change_id": "add-x", "status": "READY", "requirements": ["REQ-1"], "acceptance_ids": ["AC-1"], "tasks": [{"id": "T-1", "deliverable": "行为可用", "blocked_by": [], "acceptance_ids": ["AC-1"], "worker_packets": [{"role": "frontend"}, {"role": "backend"}], "parallel": True, "shared_contract_id": "C-1"}], "shared_contracts": [{"id": "C-1", "status": "FROZEN"}], "artifacts": {"proposal": "proposal.md", "design": "design.md", "tasks": "tasks.md", "specs": ["spec.md"]}, "validation": {"exit_code": 0}}


class ProposalContractTest(unittest.TestCase):
    def test_valid_ready_output(self) -> None:
        result = validate("output", valid_output())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_parallel_fe_be_requires_frozen_contract(self) -> None:
        payload = valid_output()
        payload["shared_contracts"][0]["status"] = "DRAFT"
        result = validate("output", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FROZEN", result.stderr)

    def test_dependency_cycle_is_rejected(self) -> None:
        payload = valid_output()
        payload["tasks"][0]["blocked_by"] = ["T-1"]
        result = validate("output", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cycle", result.stderr)

    def test_skill_has_single_design_and_no_reinterview(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("唯一技术方案", skill)
        self.assertIn("不直接联系用户", skill)
        self.assertLess(len(skill.splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
