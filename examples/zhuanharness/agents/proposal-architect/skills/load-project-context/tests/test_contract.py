import json
import subprocess
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts" / "validate-context.py"


def validate(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VALIDATOR), kind, "-"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )


class ProjectContextContractTest(unittest.TestCase):
    def test_design_basis_names_canonical_history_and_change(self) -> None:
        basis = (SKILL_ROOT / "references" / "design-basis.md").read_text(encoding="utf-8")
        self.assertIn(
            "/Users/zzzz/Documents/spec_repo/specs/common/claude/.claude/skills/load-project-knowledge",
            basis,
        )
        self.assertIn("9195fc6b341807fbc55fe67be06f8ff2bb2685bc954089e14cc1eaed47c74694", basis)
        for section in ("保留", "舍弃", "改造", "理由"):
            self.assertIn(section, basis)

    def test_skill_preserves_three_paths_and_local_knowledge(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for path in ("knowledge-agent", "llmwiki", "project-wiki"):
            self.assertIn(path, skill)
        self.assertIn("zhuanspec/knowledge", skill)
        self.assertIn("始终", skill)
        self.assertLess(len(skill.splitlines()), 180)

    def test_valid_request_maps_harness_stage(self) -> None:
        result = validate(
            "request",
            {
                "task_id": "REQ-7:C-K-1",
                "workspace_root": "/workspace/request",
                "query": "清分后商责判断规则",
                "harness_stage": "requirement-analysis",
                "coverage": "authoritative-only",
                "expert_id": 1,
                "artifact": "zhuanspec/changes/x/artifacts/knowledge/C-K-1.json",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["knowledge_stage"], "propose")

    def test_request_rejects_invalid_expert_and_missing_workspace(self) -> None:
        result = validate(
            "request",
            {
                "task_id": "REQ-7:C-K-1",
                "query": "规则",
                "harness_stage": "research",
                "coverage": "cross-stack",
                "expert_id": 9,
                "artifact": "artifacts/k.json",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workspace_root", result.stderr)
        self.assertIn("expert_id", result.stderr)

    def test_result_requires_path_reason_and_local_check(self) -> None:
        result = validate(
            "result",
            {
                "task_id": "REQ-7:C-K-1",
                "knowledge_path": "knowledge_agent",
                "knowledge_path_reason": "expert_id supplied",
                "knowledge_base_checked": False,
                "knowledge_hits": [],
                "matched_services": [],
                "coverage_check": {},
                "artifact": "artifacts/k.json",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("knowledge_base_checked", result.stderr)


if __name__ == "__main__":
    unittest.main()
