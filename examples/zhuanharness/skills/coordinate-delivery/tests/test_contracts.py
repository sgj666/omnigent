import json
import subprocess
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts" / "validate-contract.py"


def run_validator(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VALIDATOR), kind, "-"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )


def transition_payload(
    source: str,
    target: str,
    evidence_kind: str,
    *,
    version: int = 3,
    transition_id: str | None = None,
) -> dict:
    transition_id = transition_id or f"RUN-1:{source}:{target}:v{version}"
    return {
        "transition_id": transition_id,
        "run_id": "RUN-1",
        "from": source,
        "to": target,
        "expected_version": version,
        "current_version": version,
        "idempotency_key": transition_id,
        "evidence": [{"kind": evidence_kind, "ref": f"artifacts/{target}.json"}],
    }


class CoordinatorContractTest(unittest.TestCase):
    def test_skill_is_thin_and_has_traceable_design_basis(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        basis = (SKILL_ROOT / "references" / "design-basis.md").read_text(encoding="utf-8")
        self.assertLess(len(skill.splitlines()), 180)
        for source in (
            "ZhuanSpec",
            "Polly",
            "Matt Pocock",
            "Superpowers",
            "OpenSpec",
            "Ominigent",
        ):
            self.assertIn(source, basis)
        for section in ("保留", "舍弃", "理由", "版本"):
            self.assertIn(section, basis)

    def test_valid_writing_task_packet_has_both_roots(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:BE-1",
                "requirement_id": "REQ-7",
                "worker": "backend-implementer",
                "objective": "实现已冻结接口的服务端逻辑",
                "inputs": ["artifacts/contracts/order-api.yaml"],
                "deliverables": ["artifacts/BE-1/report.md"],
                "acceptance": ["unit tests pass"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "worktree-write",
                "worktree_root": "/runtime/attempt-1",
                "write_scope": ["server/**"],
                "attempt": 1,
                "hook_context": {
                    "status": "READY",
                    "attempt_root": "/runtime/attempt-1",
                    "project_settings_loaded": True,
                    "hooks_materialized": True,
                    "event_shard": "zhuanspec/changes/x/metrics/events/RUN-1/REQ-7-BE-1/1/worker.jsonl",
                },
                "parallel_group": "order-page",
                "shared_contract": {
                    "status": "FROZEN",
                    "artifact": "artifacts/contracts/order-api.yaml",
                },
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_writing_task_without_worktree_is_rejected(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:FE-1",
                "requirement_id": "REQ-7",
                "worker": "frontend-implementer",
                "objective": "实现订单页面",
                "inputs": [],
                "deliverables": ["artifacts/FE-1/report.md"],
                "acceptance": ["component tests pass"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "worktree-write",
                "write_scope": ["web/**"],
                "attempt": 1,
                "hook_context": {
                    "status": "READY",
                    "attempt_root": "/runtime/attempt-1",
                    "project_settings_loaded": True,
                    "hooks_materialized": True,
                    "event_shard": "zhuanspec/changes/x/metrics/events/RUN-1/REQ-7-FE-1/1/worker.jsonl",
                },
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree_root", result.stderr)

    def test_parallel_task_without_frozen_contract_is_rejected(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:FE-1",
                "requirement_id": "REQ-7",
                "worker": "frontend-implementer",
                "objective": "实现订单页面",
                "inputs": [],
                "deliverables": ["artifacts/FE-1/report.md"],
                "acceptance": ["webui tests pass"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "worktree-write",
                "worktree_root": "/runtime/attempt-1",
                "write_scope": ["web/**"],
                "attempt": 1,
                "hook_context": {
                    "status": "READY",
                    "attempt_root": "/runtime/attempt-1",
                    "project_settings_loaded": True,
                    "hooks_materialized": True,
                    "event_shard": "zhuanspec/changes/x/metrics/events/RUN-1/REQ-7-FE-1/1/worker.jsonl",
                },
                "parallel_group": "order-page",
                "shared_contract": {"status": "DRAFT"},
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FROZEN", result.stderr)

    def test_done_without_fresh_evidence_is_rejected(self) -> None:
        result = run_validator(
            "result-envelope",
            {
                "task_id": "REQ-7:BE-1",
                "attempt": 1,
                "status": "DONE",
                "work_type": "implementation",
                "attempt_started_at": "2026-08-12T10:00:00+08:00",
                "artifact": "artifacts/BE-1/report.md",
                "summary": "实现完成，测试通过",
                "evidence": [],
                "questions": [],
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence", result.stderr)

    def test_long_result_must_move_to_artifact(self) -> None:
        result = run_validator(
            "result-envelope",
            {
                "task_id": "REQ-7:R-1",
                "attempt": 1,
                "status": "DONE",
                "work_type": "research",
                "attempt_started_at": "2026-08-12T10:00:00+08:00",
                "artifact": "artifacts/R-1/report.md",
                "summary": "长" * 241,
                "evidence": [{
                    "kind": "artifact",
                    "ref": "artifacts/R-1/report.md",
                    "attempt": 1,
                    "produced_at": "2026-08-12T10:01:00+08:00",
                }],
                "questions": [],
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("240", result.stderr)

    def test_decision_frontier_separates_facts_and_human_decisions(self) -> None:
        result = run_validator(
            "decision-frontier",
            {
                "items": [
                    {
                        "id": "Q-1",
                        "kind": "FACT_GAP",
                        "question": "当前调用链是什么？",
                        "route": "research-engineer",
                    },
                    {
                        "id": "Q-2",
                        "kind": "HUMAN_DECISION",
                        "question": "是否承诺兼容旧字段？",
                        "route": "user",
                        "recommendation": "兼容一个版本",
                        "consequence": "需要双写并扩大回归范围",
                    },
                ]
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fact_gap_cannot_be_routed_to_user(self) -> None:
        result = run_validator(
            "decision-frontier",
            {
                "items": [
                    {
                        "id": "Q-1",
                        "kind": "FACT_GAP",
                        "question": "当前调用链是什么？",
                        "route": "user",
                    }
                ]
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FACT_GAP", result.stderr)

    def test_read_task_does_not_require_a_worktree(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:R-1",
                "requirement_id": "REQ-7",
                "worker": "research-engineer",
                "objective": "查明退款资格判断调用链",
                "inputs": ["artifacts/intake.md"],
                "deliverables": ["artifacts/R-1/report.md"],
                "acceptance": ["引用代码位置和知识来源"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "read",
                "attempt": 1,
                "hook_context": {
                    "status": "READY",
                    "attempt_root": "/runtime/attempt-1",
                    "project_settings_loaded": True,
                    "hooks_materialized": True,
                    "event_shard": "zhuanspec/changes/x/metrics/events/RUN-1/REQ-7-R-1/1/worker.jsonl",
                },
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_control_plane_write_uses_shared_workspace_without_worktree(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:RA-1",
                "requirement_id": "REQ-7",
                "worker": "requirement-analyst",
                "objective": "审查并拆分需求",
                "inputs": ["todo-app/server.mjs"],
                "deliverables": [
                    "zhuanspec/changes/x/artifacts/requirement-analysis/requirement-review.md"
                ],
                "acceptance": ["生成稳定 requirement ids"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/workspace/request",
                "task_mode": "control-plane-write",
                "write_scope": ["zhuanspec/changes/x/artifacts/requirement-analysis/**"],
                "attempt": 1,
                "hook_context": {
                    "status": "DEFERRED",
                    "reason": "Hooks are scheduled for a later milestone",
                    "attempt_root": "/workspace/request",
                },
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_control_plane_write_rejects_worktree_root(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:RA-1",
                "requirement_id": "REQ-7",
                "worker": "requirement-analyst",
                "objective": "审查并拆分需求",
                "inputs": [],
                "deliverables": ["zhuanspec/changes/x/artifacts/requirement-analysis/review.md"],
                "acceptance": ["完成审查"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/workspace/request",
                "task_mode": "control-plane-write",
                "worktree_root": "/runtime/attempt-1",
                "write_scope": ["zhuanspec/changes/x/artifacts/requirement-analysis/**"],
                "attempt": 1,
                "hook_context": {
                    "status": "DEFERRED",
                    "reason": "Hooks are scheduled for a later milestone",
                    "attempt_root": "/workspace/request",
                },
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not declare worktree_root", result.stderr)

    def test_requirement_review_is_a_supported_result_type(self) -> None:
        result = run_validator(
            "result-envelope",
            {
                "task_id": "REQ-7:RA-1",
                "attempt": 1,
                "status": "DONE",
                "work_type": "requirement-review",
                "attempt_started_at": "2026-08-12T10:00:00+08:00",
                "artifact": "zhuanspec/changes/x/artifacts/requirement-analysis/review.md",
                "summary": "需求审查完成",
                "evidence": [{
                    "kind": "artifact",
                    "ref": "sha256:abc",
                    "attempt": 1,
                    "produced_at": "2026-08-12T10:01:00+08:00",
                }],
                "questions": [],
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_workers_block_harness_precheck(self) -> None:
        result = run_validator(
            "harness-precheck",
            {
                "run_id": "RUN-FT-1",
                "status": "BLOCKED",
                "blocked_stage": "Research",
                "available_workers": [],
                "required_workers": ["research-engineer", "backend-implementer"],
                "missing_workers": ["research-engineer", "backend-implementer"],
                "available_skills": ["coordinate-delivery"],
                "required_skills": ["coordinate-delivery"],
                "missing_skills": [],
                "hook_installer": "zhuanspec init --harness",
                "project_settings_enabled": True,
                "attempt_bootstrap_available": True,
                "required_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "available_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "missing_hook_events": [],
                "artifact": "artifacts/precheck.json",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_precheck_cannot_claim_ready_with_missing_worker(self) -> None:
        result = run_validator(
            "harness-precheck",
            {
                "run_id": "RUN-FT-1",
                "status": "READY",
                "blocked_stage": "Research",
                "available_workers": [],
                "required_workers": ["research-engineer"],
                "missing_workers": ["research-engineer"],
                "available_skills": [],
                "required_skills": [],
                "missing_skills": [],
                "hook_installer": "zhuanspec init --harness",
                "project_settings_enabled": True,
                "attempt_bootstrap_available": True,
                "required_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "available_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "missing_hook_events": [],
                "artifact": "artifacts/precheck.json",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BLOCKED", result.stderr)

    def test_precheck_requires_ominigent_hook_bootstrap(self) -> None:
        result = run_validator(
            "harness-precheck",
            {
                "run_id": "RUN-HOOK-1",
                "status": "READY",
                "available_workers": [],
                "required_workers": [],
                "missing_workers": [],
                "available_skills": ["coordinate-delivery", "load-project-context"],
                "required_skills": ["coordinate-delivery", "load-project-context"],
                "missing_skills": [],
                "hook_installer": "zhuanspec init",
                "project_settings_enabled": False,
                "attempt_bootstrap_available": False,
                "required_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "available_hook_events": ["SessionStart", "Stop"],
                "missing_hook_events": ["PostToolUse"],
                "artifact": "artifacts/precheck.json",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("zhuanspec init --harness", result.stderr)
        self.assertIn("project settings", result.stderr)
        self.assertIn("attempt bootstrap", result.stderr)
        self.assertIn("BLOCKED", result.stderr)

    def test_task_packet_rejects_unmaterialized_hooks(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:R-1",
                "requirement_id": "REQ-7",
                "worker": "research-engineer",
                "objective": "查明退款资格判断调用链",
                "inputs": ["artifacts/intake.md"],
                "deliverables": ["artifacts/R-1/report.md"],
                "acceptance": ["引用代码位置和知识来源"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "read",
                "attempt": 1,
                "hook_context": {
                    "status": "BLOCKED",
                    "attempt_root": "/runtime/attempt-1",
                    "project_settings_loaded": False,
                    "hooks_materialized": False,
                    "event_shard": "",
                },
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("READY or DEFERRED", result.stderr)

    def test_deferred_hooks_do_not_block_precheck(self) -> None:
        result = run_validator(
            "harness-precheck",
            {
                "run_id": "RUN-DEFERRED-1",
                "status": "READY",
                "available_workers": ["research-engineer"],
                "required_workers": ["research-engineer"],
                "missing_workers": [],
                "available_skills": ["coordinate-delivery"],
                "required_skills": ["coordinate-delivery"],
                "missing_skills": [],
                "hooks_mode": "DEFERRED",
                "hooks_deferred_reason": "Hooks are scheduled for a later milestone",
                "project_settings_enabled": False,
                "attempt_bootstrap_available": False,
                "required_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "available_hook_events": [],
                "missing_hook_events": ["SessionStart", "PostToolUse", "Stop"],
                "artifact": "zhuanspec/changes/x/harness/precheck.json",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deferred_hook_context_is_valid_for_dispatch(self) -> None:
        result = run_validator(
            "task-packet",
            {
                "task_id": "REQ-7:R-1",
                "requirement_id": "REQ-7",
                "worker": "research-engineer",
                "objective": "查明退款资格判断调用链",
                "inputs": ["zhuanspec/changes/x/artifacts/intake.md"],
                "deliverables": ["zhuanspec/changes/x/artifacts/R-1/report.md"],
                "acceptance": ["引用代码位置和知识来源"],
                "workspace_root": "/workspace/request",
                "attempt_root": "/runtime/attempt-1",
                "task_mode": "read",
                "attempt": 1,
                "hook_context": {
                    "status": "DEFERRED",
                    "reason": "Hooks are scheduled for a later milestone",
                    "attempt_root": "/runtime/attempt-1",
                },
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_artifact_record_requires_sha256_and_current_attempt(self) -> None:
        result = run_validator(
            "artifact-record",
            {
                "artifact_id": "ART-1",
                "run_id": "RUN-1",
                "task_id": "REQ-7:R-1",
                "type": "research-report",
                "path": "zhuanspec/changes/x/artifacts/R-1/report.md",
                "content_hash": "not-a-sha256",
                "created_at": "2026-08-12T10:01:00+08:00",
                "producer_attempt": 0,
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256", result.stderr)
        self.assertIn("positive integer", result.stderr)

    def test_runtime_mapping_is_explicit(self) -> None:
        runtime = (SKILL_ROOT / "references" / "task-packet.md").read_text()
        for tool in (
            "sys_session_send",
            "sys_read_inbox",
            "sys_session_get_history",
            "sys_cancel_task",
        ):
            self.assertIn(tool, runtime)
        self.assertIn("zhuanspec/changes", runtime)

    def test_global_runtime_skills_are_not_inherited(self) -> None:
        basis = (SKILL_ROOT / "references" / "design-basis.md").read_text(encoding="utf-8")
        self.assertIn("skills: none", basis)
        self.assertIn("remote_skills", basis)
        self.assertIn("全局共享 Skill", basis)
        self.assertIn("Attempt-start adapter", basis)

    def test_test_evidence_must_be_successful_and_current_attempt(self) -> None:
        result = run_validator(
            "result-envelope",
            {
                "task_id": "REQ-7:T-1",
                "attempt": 2,
                "status": "DONE",
                "work_type": "test",
                "attempt_started_at": "2026-08-12T10:00:00+08:00",
                "artifact": "artifacts/T-1/report.md",
                "summary": "测试完成",
                "evidence": [{
                    "kind": "test",
                    "command": "npm test",
                    "exit_code": 1,
                    "summary": "1 failed",
                    "attempt": 1,
                    "produced_at": "2026-08-12T09:59:00+08:00",
                }],
                "questions": [],
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_code must be 0", result.stderr)
        self.assertIn("match envelope attempt", result.stderr)
        self.assertIn("predates", result.stderr)

    def test_implementation_done_requires_change_reference(self) -> None:
        result = run_validator(
            "result-envelope",
            {
                "task_id": "REQ-7:BE-1",
                "attempt": 1,
                "status": "DONE",
                "work_type": "implementation",
                "attempt_started_at": "2026-08-12T10:00:00+08:00",
                "artifact": "artifacts/BE-1/report.md",
                "summary": "实现完成",
                "evidence": [{
                    "kind": "test",
                    "command": "pytest",
                    "exit_code": 0,
                    "summary": "12 passed",
                    "attempt": 1,
                    "produced_at": "2026-08-12T10:01:00+08:00",
                }],
                "questions": [],
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit or change", result.stderr)

    def test_delivery_state_order_is_explicit_and_legal(self) -> None:
        edges = [
            ("intake", "preflight", "run-request"),
            ("preflight", "requirement", "harness-precheck"),
            ("requirement", "research", "requirement-manifest"),
            ("research", "proposal", "research-artifact"),
            ("proposal", "planning", "proposal-manifest"),
            ("planning", "implementation", "plan-approval"),
            ("implementation", "integration", "implementation-handoff"),
            ("integration", "testing", "candidate-vector"),
            ("testing", "verification", "test-result"),
            ("verification", "review", "verification-result"),
            ("review", "knowledge_close", "review-result"),
            ("knowledge_close", "archive", "knowledge-closure"),
            ("archive", "pending_delivery", "archive-result"),
            ("pending_delivery", "delivered", "human-approval"),
        ]
        for version, (source, target, evidence_kind) in enumerate(edges):
            with self.subTest(source=source, target=target):
                result = run_validator(
                    "transition",
                    transition_payload(source, target, evidence_kind, version=version),
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_implementation_cannot_skip_integration(self) -> None:
        result = run_validator(
            "transition",
            transition_payload("implementation", "testing", "implementation-handoff"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("illegal transition", result.stderr)

    def test_verification_requires_test_result(self) -> None:
        result = run_validator(
            "transition",
            transition_payload("testing", "verification", "candidate-vector"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("test-result", result.stderr)

    def test_delivery_requires_human_approval(self) -> None:
        result = run_validator(
            "transition",
            transition_payload("pending_delivery", "delivered", "archive-result"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("human-approval", result.stderr)

    def test_stale_expected_version_is_rejected(self) -> None:
        payload = transition_payload("integration", "testing", "candidate-vector")
        payload["current_version"] = payload["expected_version"] + 1
        result = run_validator("transition", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale", result.stderr)

    def test_missing_idempotency_key_is_rejected(self) -> None:
        payload = transition_payload("integration", "testing", "candidate-vector")
        del payload["idempotency_key"]
        result = run_validator("transition", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("idempotency_key", result.stderr)

    def test_same_transition_id_can_be_replayed_idempotently(self) -> None:
        payload = transition_payload("testing", "testing", "candidate-vector")
        payload["applied_transition_id"] = payload["transition_id"]
        result = run_validator("transition", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_different_transition_id_cannot_self_transition(self) -> None:
        payload = transition_payload("testing", "testing", "candidate-vector")
        payload["applied_transition_id"] = "RUN-1:integration:testing:v2"
        result = run_validator("transition", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("idempotent replay", result.stderr)

    def test_retired_states_are_rejected_and_archive_is_known(self) -> None:
        for retired in ("SelfCheck", "ReverseAlignment", "blocked"):
            with self.subTest(retired=retired):
                payload = transition_payload(retired, "archive", "knowledge-closure")
                result = run_validator("transition", payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("known state", result.stderr)

        result = run_validator(
            "transition",
            transition_payload("knowledge_close", "archive", "knowledge-closure"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovery_and_simple_path_policies_are_explicit(self) -> None:
        workflow = (SKILL_ROOT / "references" / "workflow-state-machine.md").read_text()
        gate = (SKILL_ROOT / "references" / "gate-policy.md").read_text()
        packet = (SKILL_ROOT / "references" / "task-packet.md").read_text()
        self.assertIn("不得重跑", workflow)
        self.assertIn("Ledger", workflow)
        self.assertIn("Artifact Registry", workflow)
        self.assertIn("Runaway", workflow)
        self.assertIn("先取消", workflow)
        self.assertIn("简单工作项", gate)
        self.assertIn("Research Engineer", gate)
        self.assertIn("Artifact", packet)
        self.assertIn("240", packet)


if __name__ == "__main__":
    unittest.main()
