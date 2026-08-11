import json
import tempfile
import unittest
from pathlib import Path

from goai_control_tower.foundation import WorkspaceRequiredCIPort, provider_by_id
from goai_control_tower.track1 import replay_provider, run_demo


class Track1Tests(unittest.TestCase):
    def test_live_without_verifier_workspace_fails_closed(self):
        report = WorkspaceRequiredCIPort().run({"attempt": 1})
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["failure_signature"], "VERIFIER_WORKSPACE_UNAVAILABLE")

    def test_failed_verification_recovers_and_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = run_demo(Path(directory), provider_id="opencode")
            self.assertEqual(pack["summary"]["final_state"], "CLOSED")
            self.assertEqual(pack["summary"]["hidden_verification"], "pass")
            self.assertEqual(len(pack["agents"]), 8)
            self.assertEqual(len(pack["skills"]), 12)
            transitions = [event for event in pack["trace"] if event["event_type"] == "STATE_TRANSITION"]
            self.assertTrue(any(event["payload"]["to"] == "PATCHED" and event["payload"]["metadata"].get("failure_signature") for event in transitions))
            self.assertTrue(any(event["event_type"] == "APPROVAL_DECIDED" for event in pack["trace"]))
            self.assertTrue(all(item["trace_id"] == pack["trace_id"] for item in pack["evidence"]))

    def test_same_fixture_can_replay_against_provider_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            local = replay_provider("scripted-local", Path(directory) / "local")
            opencode = replay_provider("opencode", Path(directory) / "opencode")
            for replay in (local, opencode):
                self.assertEqual(replay["task_fixture"], "T1-codeops-demo-v1")
                self.assertEqual(replay["final_state"], "CLOSED")
                self.assertEqual(replay["hidden_verification"], "pass")
            self.assertEqual(local["evidence_schema"], opencode["evidence_schema"])

    def test_fixture_provider_executes_patch_and_hidden_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = run_demo(Path(directory), provider_id="fixture-local")
            self.assertEqual(pack["summary"]["final_state"], "CLOSED")
            self.assertEqual(pack["summary"]["execution_mode"], "real-fixture-subprocess")
            self.assertEqual(pack["summary"]["changed_files"], ["src/retry_guard.py"])
            executions = [item for item in pack["artifacts"] if item["artifact_type"] == "PatchBundle"]
            self.assertEqual(len(executions), 2)
            self.assertEqual(executions[0]["payload"]["status"], "PATCHED")
            self.assertEqual(executions[1]["payload"]["status"], "PATCHED")
            self.assertNotIn("tests", executions[0]["payload"])
            verifications = [item for item in pack["artifacts"] if item["artifact_type"] == "VerificationReport"]
            self.assertEqual(verifications[0]["payload"]["verifier_context"], "artifact+spec+independent-test")
            self.assertEqual(verifications[0]["payload"]["provider"], "subprocess-ci")
            self.assertEqual(verifications[0]["payload"]["hidden"], "fail")
            self.assertEqual(verifications[0]["payload"]["failure_signature"], "REGRESSION_TIMEOUT_GUARD")
            self.assertEqual(verifications[1]["payload"]["hidden"], "pass")
            workspace = Path(pack["summary"]["workspace"])
            source = (workspace / "src" / "retry_guard.py").read_text(encoding="utf-8")
            self.assertIn("if idempotency_key is not None", source)
            self.assertFalse((workspace / "hidden_tests").exists())
            persisted = json.loads((Path(directory) / "evidence" / "T1-codeops-demo.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["evidence_pack_relative_path"], "evidence/T1-codeops-demo.json")
            self.assertEqual(persisted["input_payload"]["symptom"], "request timeout after retry")

    def test_fixture_provider_rejects_unapproved_file_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = provider_by_id(
                "fixture-local",
                workspace_root=root / "workspaces",
                fixture_root=Path(__file__).parents[1] / "fixtures" / "track1" / "demo-service",
            )
            with self.assertRaises(ValueError):
                provider.execute({"attempt": 1, "workspace_id": "scope-test", "approved_scope": ["tests/test_public.py"]})
            self.assertFalse((root / "workspaces" / "scope-test").exists())
