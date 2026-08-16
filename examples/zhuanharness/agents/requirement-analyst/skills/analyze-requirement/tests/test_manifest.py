import json
import subprocess
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts" / "validate-manifest.py"
BRIEF_VALIDATOR = SKILL_ROOT / "scripts" / "validate-brief.py"


def run_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VALIDATOR), "-"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )


def run_brief_validator(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(BRIEF_VALIDATOR), "-"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )


def valid_manifest() -> dict:
    return {
        "requirement_id": "REQ-101",
        "status": "READY",
        "summary": "支持用户按状态筛选订单，并保留原有默认列表行为。",
        "split_basis": "business-capability",
        "capabilities": [
            {
                "id": "CAP-1",
                "title": "订单状态筛选",
                "objective": "用户可选择状态并看到匹配订单",
                "acceptance_criteria": ["AC-1"],
                "source_refs": ["input:user-request"],
            }
        ],
        "acceptance_criteria": [
            {
                "id": "AC-1",
                "statement": "WHEN 用户选择已完成 THEN 列表只展示已完成订单",
                "observable": True,
                "source_refs": ["input:user-request"],
            }
        ],
        "issues": [],
        "research_requests": [],
        "user_decisions": [],
        "traceability": [
            {"source_ref": "input:user-request", "targets": ["CAP-1", "AC-1"]}
        ],
        "artifacts": {
            "review": "artifacts/requirement-analysis/requirement-review.md",
            "manifest": "artifacts/requirement-analysis/requirement-manifest.json",
        },
    }


class RequirementManifestTest(unittest.TestCase):
    def test_requirement_brief_carries_fresh_context_and_artifact_refs(self) -> None:
        result = run_brief_validator(
            {
                "task_id": "REQ-101:requirement-analysis:1",
                "requirement_id": "REQ-101",
                "change_id": "add-order-filter",
                "workspace_root": "/workspace/project",
                "attempt_root": "/runtime/attempt-1",
                "goal": "支持用户按状态筛选订单",
                "known_scope": [],
                "existing_decisions": [],
                "artifact_refs": ["input/user-request.md"],
                "hook_context": {
                    "status": "DEFERRED",
                    "reason": "Hooks are scheduled for a later milestone",
                },
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requirement_brief_rejects_missing_artifact_refs(self) -> None:
        result = run_brief_validator(
            {
                "task_id": "REQ-101:requirement-analysis:1",
                "requirement_id": "REQ-101",
                "change_id": "add-order-filter",
                "workspace_root": "/workspace/project",
                "attempt_root": "/runtime/attempt-1",
                "goal": "支持用户按状态筛选订单",
                "known_scope": [],
                "existing_decisions": [],
                "artifact_refs": [],
                "hook_context": {"status": "DEFERRED", "reason": "later"},
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifact_refs", result.stderr)

    def test_ready_manifest_with_traceable_acceptance_is_valid(self) -> None:
        result = run_validator(valid_manifest())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fact_gap_cannot_be_sent_to_user(self) -> None:
        manifest = valid_manifest()
        manifest["status"] = "NEEDS_USER_DECISION"
        manifest["issues"] = [
            {"id": "ISSUE-1", "category": "FACT_GAP", "summary": "现有接口是否返回状态字段"}
        ]
        manifest["user_decisions"] = [
            {
                "id": "UD-1",
                "issue_id": "ISSUE-1",
                "kind": "fact",
                "question": "现有接口是否返回状态字段？",
                "options": ["是", "否"],
            }
        ]
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("research_requests", result.stderr)

    def test_technical_layer_split_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["split_basis"] = "technical-layer"
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("business-capability", result.stderr)

    def test_ready_without_acceptance_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["capabilities"][0]["acceptance_criteria"] = []
        manifest["acceptance_criteria"] = []
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acceptance", result.stderr)

    def test_valid_scope_decision_is_accepted(self) -> None:
        manifest = valid_manifest()
        manifest["status"] = "NEEDS_USER_DECISION"
        manifest["issues"] = [
            {"id": "ISSUE-2", "category": "BUSINESS_DECISION", "summary": "历史订单是否纳入筛选"}
        ]
        manifest["user_decisions"] = [
            {
                "id": "UD-2",
                "issue_id": "ISSUE-2",
                "kind": "scope_choice",
                "question": "筛选能力是否包含历史订单？",
                "recommended_option_id": "OPT-2",
                "options": [
                    {
                        "id": "OPT-1",
                        "label": "包含全部历史订单",
                        "impact": "需要兼容历史数据并补充回溯验证",
                    },
                    {
                        "id": "OPT-2",
                        "label": "仅包含上线后订单",
                        "impact": "改动范围较小，但历史订单不可筛选",
                    },
                ],
            }
        ]
        result = run_validator(manifest)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_user_decision_requires_recommendation_and_option_impacts(self) -> None:
        manifest = valid_manifest()
        manifest["status"] = "NEEDS_USER_DECISION"
        manifest["issues"] = [
            {"id": "ISSUE-2", "category": "BUSINESS_DECISION", "summary": "历史订单范围"}
        ]
        manifest["user_decisions"] = [
            {
                "id": "UD-2",
                "issue_id": "ISSUE-2",
                "kind": "scope_choice",
                "question": "筛选能力是否包含历史订单？",
                "options": ["包含", "不包含"],
            }
        ]
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recommended_option_id", result.stderr)
        self.assertIn("impact", result.stderr)

    def test_scope_rework_requires_a_scope_conflict(self) -> None:
        manifest = valid_manifest()
        manifest["status"] = "NEEDS_SCOPE_REWORK"
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SCOPE_CONFLICT", result.stderr)

    def test_every_capability_and_acceptance_source_is_traceable(self) -> None:
        manifest = valid_manifest()
        manifest["acceptance_criteria"][0]["source_refs"] = ["input:missing"]
        result = run_validator(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source_ref", result.stderr)

    def test_worker_never_contacts_user_directly(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text()
        protocol = (SKILL_ROOT / "references" / "analysis-protocol.md").read_text()
        self.assertIn("不得直接联系用户", skill)
        self.assertIn("Research Request", protocol)
        self.assertIn("Result Envelope", protocol)

    def test_worker_uses_lightweight_context_before_analysis_and_does_not_write_proposal(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text()
        self.assertIn("load-project-context", skill)
        self.assertIn("不编写 `proposal.md`", skill)
        self.assertIn("Proposal Architect", skill)

    def test_skill_name_is_short_and_not_bundle_namespaced(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text()
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text()
        self.assertIn("name: analyze-requirement", skill)
        self.assertIn("$analyze-requirement", metadata)


if __name__ == "__main__":
    unittest.main()
