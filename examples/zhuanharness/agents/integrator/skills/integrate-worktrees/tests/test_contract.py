import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate-integration.py"


def validate(kind: str, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(VALIDATOR), kind, "-"], input=json.dumps(payload), text=True, capture_output=True, check=False)


def valid_request() -> dict:
    return {"task_id": "I-1", "change_id": "add-x", "attempt_root": "/attempt", "control_repository_id": "control", "base_vector": [{"repository_id": "repo", "base_sha": "a" * 40, "materialize_ref": "refs/base"}], "handoffs": [{"task_id": "T-1", "repository_id": "repo", "ref": "refs/zhuanspec/add-x/handoff/T-1/r1", "output_sha": "b" * 40, "base_sha": "a" * 40, "commits": ["b" * 40], "changed_paths": ["src/a.py"], "owned_paths": ["src"]}], "task_order": ["T-1"], "artifact_snapshot": {"ref": "refs/spec"}, "required_checks": ["test"], "integration_attempt": 1, "output_manifest": "manifest.json", "hook_context": {"status": "DEFERRED"}}


class IntegrationContractTest(unittest.TestCase):
    def test_valid_request(self) -> None:
        result = validate("request", valid_request())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_path_outside_ownership_is_rejected(self) -> None:
        payload = valid_request()
        payload["handoffs"][0]["changed_paths"] = ["other/a.py"]
        result = validate("request", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("owned_paths", result.stderr)

    def test_integrated_requires_complete_manifest(self) -> None:
        payload = {"change_id": "add-x", "status": "INTEGRATED", "base_vector": [{"repository_id": "repo"}], "input_handoffs": ["ref"], "candidate_vector": [{"repository_id": "repo"}], "manifest": {"status": "INCOMPLETE"}, "applied_commits": ["sha"], "checks": [{"exit_code": 0}], "conflicts": [], "unchanged_repositories": []}
        result = validate("result", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("COMPLETE", result.stderr)

    def test_integrated_accepts_empty_conflicts_and_unchanged_repositories(self) -> None:
        payload = {"change_id": "add-x", "status": "INTEGRATED", "base_vector": [{"repository_id": "repo"}], "input_handoffs": ["ref"], "candidate_vector": [{"repository_id": "repo"}], "manifest": {"status": "COMPLETE"}, "applied_commits": ["sha"], "checks": [{"exit_code": 0}], "conflicts": [], "unchanged_repositories": []}
        result = validate("result", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_integrator_does_not_resolve_semantic_conflicts(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("不得选择 ours/theirs", skill)
        self.assertIn("不运行 `git worktree add`", skill)
        self.assertLess(len(skill.splitlines()), 120)


if __name__ == "__main__":
    unittest.main()
