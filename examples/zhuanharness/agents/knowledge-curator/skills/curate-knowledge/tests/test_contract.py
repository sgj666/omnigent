import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-knowledge.py"


def validate(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), kind, "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


class KnowledgeContractTest(unittest.TestCase):
    def test_verified_candidate_is_valid(self) -> None:
        payload = {"change_id": "fix-x", "candidates": [{"id": "K-1", "category": "troubleshooting", "title": "根因", "claim": "规则", "source_change": "fix-x", "evidence_refs": ["ref"], "confidence": 0.9, "policy_impact": False, "sensitive": False, "action": "create"}]}
        result = validate("candidates", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_policy_candidate_requires_decision(self) -> None:
        payload = {"change_id": "fix-x", "candidates": [{"id": "K-1", "category": "best-practices", "title": "政策", "claim": "规则", "source_change": "fix-x", "evidence_refs": ["ref"], "confidence": 0.9, "policy_impact": True, "sensitive": False, "action": "create"}]}
        result = validate("candidates", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("human decision", result.stderr)

    def test_candidate_cannot_appear_in_two_result_sets(self) -> None:
        payload = {"change_id": "fix-x", "status": "CURATED", "created": ["K-1"], "updated": ["K-1"], "deprecated": [], "rejected": [], "decision_required": [], "index_path": "zhuanspec/knowledge/index.md", "evidence_refs": ["ref"]}
        result = validate("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple", result.stderr)

    def test_curated_accepts_empty_non_selected_result_sets(self) -> None:
        payload = {"change_id": "fix-x", "status": "CURATED", "created": ["K-1"], "updated": [], "deprecated": [], "rejected": [], "decision_required": [], "index_path": "zhuanspec/knowledge/index.md", "evidence_refs": ["ref"]}
        result = validate("result", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_skill_separates_hooks_and_curation(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Hooks 负责采集", skill)
        self.assertIn("不直接联系用户", skill)
        self.assertLess(len(skill.splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
