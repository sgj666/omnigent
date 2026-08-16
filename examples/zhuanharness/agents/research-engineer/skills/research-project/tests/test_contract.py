import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-research.py"


def validate(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), kind, "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def valid_result() -> dict:
    return {"task_id": "T-R-1", "research_id": "R-1", "status": "ANSWERED", "question": "入口？", "findings": [{"id": "F-1", "statement": "入口存在", "kind": "source_fact", "confidence": "high", "source_refs": ["src"], "code_anchors": ["repo:a.py:1"], "affects": ["AC-1"], "verification": "verified"}], "conflicts": [], "unknowns": [], "decision_gaps": [], "repositories_checked": ["repo"], "artifacts": {"json": "R-1.json", "report": "R-1.md"}}


class ResearchContractTest(unittest.TestCase):
    def test_valid_result(self) -> None:
        result = validate("result", valid_result())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_answered_rejects_unknowns(self) -> None:
        payload = valid_result()
        payload["unknowns"] = ["未确认"]
        result = validate("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANSWERED", result.stderr)

    def test_delivery_fact_requires_code_anchor(self) -> None:
        payload = valid_result()
        payload["findings"][0]["code_anchors"] = []
        result = validate("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("code_anchors", result.stderr)

    def test_role_is_read_only_and_does_not_ask_user(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("全程只读", skill)
        self.assertIn("不直接联系用户", skill)
        self.assertLess(len(skill.splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
