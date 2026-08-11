import tempfile
import unittest
from pathlib import Path

from goai_control_tower.native_mcp import (
    AuthorityError,
    AuthorizationError,
    ConflictError,
    SQLiteStateAuthority,
)


def _fail_report(signature: str) -> dict:
    return {
        "verdict": "FAIL",
        "commands": ["pytest tests/"],
        "verifier_context": "independent-workspace",
        "failure_signature": signature,
    }


class P1StateToolsTests(unittest.TestCase):
    def _drive_to_located(self, authority: SQLiteStateAuthority, task_id: str) -> int:
        authority.create_task(task_id, "codeops", {"summary": "demo"})
        authority.put_artifact(task_id, "IssueCluster", "codeops-intake", {"clusters": []}, [], 0)
        authority.transition(task_id, "FUSED", "codeops-intake", "fused", 0)
        authority.put_artifact(task_id, "RiskAssessment", "codeops-triage", {"level": "high"}, [], 1)
        authority.transition(task_id, "TRIAGED", "codeops-triage", "triaged", 1)
        authority.put_artifact(task_id, "EnvironmentSnapshot", "codeops-env-bootstrap", {"os": "linux"}, [], 2)
        authority.transition(task_id, "BOOTSTRAPPED", "codeops-env-bootstrap", "ready", 2)
        authority.put_artifact(task_id, "RootCauseHypotheses", "codeops-repo-analyst", {"hypotheses": []}, [], 3)
        authority.transition(task_id, "LOCATED", "codeops-repo-analyst", "located", 3)
        return 4

    def test_state_describe_verifier_at_located(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            self._drive_to_located(authority, "T-D1")
            descriptor = authority.state_describe("T-D1", "codeops-verifier")
            self.assertEqual(descriptor["state"], "LOCATED")
            self.assertEqual(descriptor["you_are"], "codeops-verifier")
            self.assertIn("READONLY_VERIFYING", descriptor["allowed_transitions"])
            self.assertIn("NEEDS_HUMAN", descriptor["allowed_transitions"])
            self.assertIn("PLANNED", descriptor["blocked_transitions"])
            self.assertEqual(descriptor["expected_outputs"], [])
            self.assertTrue(descriptor["duty"])
            self.assertEqual(len(descriptor["available_inputs"]), 4)
            self.assertEqual(descriptor["breaker_tripped"], [])

    def test_state_describe_intake_owns_nothing_at_located(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            self._drive_to_located(authority, "T-D2")
            descriptor = authority.state_describe("T-D2", "codeops-intake")
            self.assertEqual(descriptor["allowed_transitions"], [])
            self.assertIn("READONLY_VERIFYING", descriptor["blocked_transitions"])

    def test_state_describe_exit_criteria_in_verifying(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_located(authority, "T-D3")
            authority.transition("T-D3", "READONLY_VERIFYING", "codeops-verifier", "verify", version)
            descriptor = authority.state_describe("T-D3", "codeops-verifier")
            self.assertIn("VerificationReport", descriptor["expected_outputs"])
            criteria = {item["target"]: item["requires"] for item in descriptor["exit_criteria"]}
            self.assertIn("READONLY_VERIFIED", criteria)
            self.assertIn("verdict=PASS", criteria["READONLY_VERIFIED"])

    def test_breaker_trips_on_third_same_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_located(authority, "T-B1")
            for _ in range(3):
                authority.transition("T-B1", "READONLY_VERIFYING", "codeops-verifier", "verify", version)
                version += 1
                authority.put_artifact("T-B1", "VerificationReport", "codeops-verifier", _fail_report("sig-timeout"), [], version)
                authority.transition("T-B1", "NEEDS_HUMAN", "codeops-verifier", "fail", version)
                version += 1
            with self.assertRaises(AuthorizationError) as context:
                authority.transition("T-B1", "READONLY_VERIFYING", "codeops-verifier", "retry again", version)
            self.assertIn("FAILURE_SIGNATURE_BREAKER_TRIPPED", str(context.exception))
            self.assertIn("sig-timeout", str(context.exception))

    def test_breaker_allows_retry_below_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_located(authority, "T-B2")
            for _ in range(2):
                authority.transition("T-B2", "READONLY_VERIFYING", "codeops-verifier", "verify", version)
                version += 1
                authority.put_artifact("T-B2", "VerificationReport", "codeops-verifier", _fail_report("sig-flaky"), [], version)
                authority.transition("T-B2", "NEEDS_HUMAN", "codeops-verifier", "fail", version)
                version += 1
            task = authority.transition("T-B2", "READONLY_VERIFYING", "codeops-verifier", "third attempt", version)
            self.assertEqual(task["state"], "READONLY_VERIFYING")

    def test_breaker_ignores_distinct_signatures(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_located(authority, "T-B3")
            for index in range(3):
                authority.transition("T-B3", "READONLY_VERIFYING", "codeops-verifier", "verify", version)
                version += 1
                authority.put_artifact("T-B3", "VerificationReport", "codeops-verifier", _fail_report("sig-%d" % index), [], version)
                authority.transition("T-B3", "NEEDS_HUMAN", "codeops-verifier", "fail", version)
                version += 1
            task = authority.transition("T-B3", "READONLY_VERIFYING", "codeops-verifier", "new signature ok", version)
            self.assertEqual(task["state"], "READONLY_VERIFYING")

    def test_state_describe_reports_breaker_status(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_located(authority, "T-B4")
            for _ in range(3):
                authority.transition("T-B4", "READONLY_VERIFYING", "codeops-verifier", "verify", version)
                version += 1
                authority.put_artifact("T-B4", "VerificationReport", "codeops-verifier", _fail_report("sig-x"), [], version)
                authority.transition("T-B4", "NEEDS_HUMAN", "codeops-verifier", "fail", version)
                version += 1
            descriptor = authority.state_describe("T-B4", "codeops-verifier")
            self.assertEqual(descriptor["failure_signature_counts"], {"sig-x": 3})
            self.assertEqual(descriptor["breaker_tripped"], ["sig-x"])


class P1SideEffectLedgerTests(unittest.TestCase):
    def test_intent_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S1", "codeops", {"summary": "demo"})
            first = authority.record_side_effect_intent("T-S1", "branch_prepare", "fix-retry-guard", {"branch": "fix/retry-guard"}, "codeops-executor")
            self.assertTrue(first["created"])
            replay = authority.record_side_effect_intent("T-S1", "branch_prepare", "fix-retry-guard", {"branch": "fix/retry-guard"}, "codeops-executor")
            self.assertFalse(replay["created"])
            self.assertEqual(first["effect_id"], replay["effect_id"])

    def test_intent_key_reuse_with_different_intent_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S2", "codeops", {"summary": "demo"})
            authority.record_side_effect_intent("T-S2", "branch_prepare", "k1", {"branch": "a"}, "codeops-executor")
            with self.assertRaises(ConflictError):
                authority.record_side_effect_intent("T-S2", "branch_prepare", "k1", {"branch": "b"}, "codeops-executor")

    def test_unauthorized_actor_cannot_write_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S3", "codeops", {"summary": "demo"})
            with self.assertRaises(AuthorizationError):
                authority.record_side_effect_intent("T-S3", "branch_prepare", "k1", {}, "codeops-intake")

    def test_result_lifecycle_and_recovery_reread(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S4", "codeops", {"summary": "demo"})
            intent = authority.record_side_effect_intent("T-S4", "notify", "n1", {"channel": "matrix"}, "codeops-lead")
            updated = authority.record_side_effect_result(intent["effect_id"], "EXECUTED", {"event_id": "$evt"}, "codeops-lead")
            self.assertEqual(updated["status"], "EXECUTED")
            ledger = authority.list_side_effects("T-S4")
            self.assertEqual(len(ledger["side_effects"]), 1)
            self.assertEqual(ledger["side_effects"][0]["result"], {"event_id": "$evt"})

    def test_invalid_result_status_and_unknown_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S5", "codeops", {"summary": "demo"})
            intent = authority.record_side_effect_intent("T-S5", "notify", "n1", {}, "codeops-lead")
            with self.assertRaises(AuthorityError):
                authority.record_side_effect_result(intent["effect_id"], "INTENT", {}, "codeops-lead")
            with self.assertRaises(AuthorityError):
                authority.record_side_effect_result("fx_missing", "EXECUTED", {}, "codeops-lead")

    def test_ledger_events_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-S6", "codeops", {"summary": "demo"})
            intent = authority.record_side_effect_intent("T-S6", "notify", "n1", {}, "codeops-lead")
            authority.record_side_effect_result(intent["effect_id"], "FAILED", {"error": "timeout"}, "codeops-lead")
            pack = authority.evidence_pack("T-S6")
            event_types = [event["event_type"] for event in pack["events"]]
            self.assertIn("SIDE_EFFECT_INTENT", event_types)
            self.assertIn("SIDE_EFFECT_RESULT", event_types)


if __name__ == "__main__":
    unittest.main()
