import json
import tempfile
import unittest
from pathlib import Path

from exoflow.native_mcp import AuthorityError, AuthorizationError, ConflictError, SQLiteStateAuthority, handle_mcp_jsonrpc


class NativeMCPTests(unittest.TestCase):
    def test_sqlite_authority_enforces_cas_and_matrix_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            created = authority.create_task("T1", "software-engineering", {"issue": "timeout"}, "trace-1")
            self.assertTrue(created["created"])
            replay = authority.create_task("T1", "software-engineering", {"issue": "timeout"}, "trace-ignored")
            self.assertFalse(replay["created"])
            authority.transition("T1", "FUSED", "codeops-intake", "fused", 0)
            with self.assertRaises(ConflictError):
                authority.transition("T1", "TRIAGED", "codeops-triage", "stale", 0)
            authority.transition("T1", "TRIAGED", "codeops-triage", "triaged", 1)
            authority.transition("T1", "BOOTSTRAPPED", "codeops-env-bootstrap", "workspace", 2)
            authority.transition("T1", "LOCATED", "codeops-repo-analyst", "located", 3)
            authority.transition("T1", "PLANNED", "codeops-plan", "planned", 4)
            approval = authority.request_approval(
                "T1",
                "codeops-plan",
                {"files": ["src/retry_guard.py"], "commands": ["pytest"]},
                "AWAITING_APPROVAL",
                5,
            )
            self.assertEqual(approval["expected_decision_version"], 6)
            authority.transition("T1", "AWAITING_APPROVAL", "codeops-plan", "approval requested", 5)
            with self.assertRaises(ConflictError):
                authority.decide_approval(approval["approval_id"], "reviewer", "APPROVED", "wrong", "!room:local", "$event")
            decision = authority.decide_approval(
                approval["approval_id"],
                "reviewer",
                "APPROVED",
                approval["scope_digest"],
                "!room:local",
                "$event",
            )
            self.assertEqual(decision["decision_evidence"]["event_id"], "$event")
            status = authority.get_approval(approval["approval_id"])
            self.assertEqual(status["status"], "APPROVED")
            self.assertEqual(status["scope"]["files"], ["src/retry_guard.py"])
            artifact = authority.put_artifact("T1", "ChangePlan", "codeops-plan", {"plan": "bounded"}, [], 6)
            self.assertEqual(artifact["state_version"], 6)
            with self.assertRaises(AuthorizationError):
                authority.transition("T1", "PATCHED", "codeops-executor", "missing patch evidence", 6)
            with self.assertRaises(AuthorizationError):
                authority.put_artifact(
                    "T1",
                    "PatchBundle",
                    "codeops-executor",
                    {"approval_id": approval["approval_id"], "changed_files": ["src/out_of_scope.py"]},
                    [],
                    6,
                )
            patch = authority.put_artifact(
                "T1",
                "PatchBundle",
                "codeops-executor",
                {"approval_id": approval["approval_id"], "changed_files": ["src/retry_guard.py"], "diff_digest": "sha256:test"},
                [],
                6,
            )
            self.assertEqual(patch["producer"], "codeops-executor")
            patched = authority.transition("T1", "PATCHED", "codeops-executor", "approved patch published", 6)
            self.assertEqual(patched["state_version"], 7)
            pack = authority.evidence_pack("T1")
            self.assertEqual(pack["task"]["state"], "PATCHED")
            self.assertEqual(pack["approvals"][0]["status"], "APPROVED")
            self.assertEqual(pack["artifacts"][0]["content_digest"], artifact["content_digest"])

    def test_mcp_protocol_authenticates_and_binds_actor(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            identities = {"lead-token": "codeops-lead", "intake-token": "codeops-intake"}

            status, initialized = handle_mcp_jsonrpc(
                authority,
                identities,
                "/mcp",
                {"Authorization": "Bearer lead-token"},
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            self.assertEqual(status, 200)
            self.assertEqual(initialized["result"]["protocolVersion"], "2025-03-26")

            status, listed = handle_mcp_jsonrpc(
                authority,
                identities,
                "/mcp",
                {"Authorization": "Bearer lead-token"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["result"]["tools"]), 12)

            status, created = handle_mcp_jsonrpc(
                authority,
                identities,
                "/mcp",
                {"Authorization": "Bearer lead-token"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "task_create", "arguments": {"task_id": "HTTP-1", "domain": "software-engineering", "input_payload": {"issue": "timeout"}}}},
            )
            self.assertEqual(status, 200)
            self.assertTrue(created["result"]["structuredContent"]["created"])

            status, denied = handle_mcp_jsonrpc(
                authority,
                identities,
                "/mcp",
                {"Authorization": "Bearer intake-token"},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "task_create", "arguments": {"task_id": "HTTP-2", "domain": "software-engineering", "input_payload": {}}}},
            )
            self.assertEqual(status, 200)
            self.assertEqual(denied["error"]["data"]["authority_code"], "UNAUTHORIZED")

            status, missing_auth = handle_mcp_jsonrpc(
                authority,
                identities,
                "/mcp",
                {"Authorization": "Bearer wrong-token"},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
            )
            self.assertEqual(status, 401)
            self.assertEqual(missing_auth["error"], "invalid worker identity token")
    def test_readonly_branch_reaches_evidence_packed_and_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-RO", "software-engineering", {"issue": "read-only analysis"}, "trace-ro")
            authority.put_artifact("T-RO", "IssueCluster", "codeops-intake", {"cluster": ["issue-1"]}, [], 0)
            authority.transition("T-RO", "FUSED", "codeops-intake", "fused", 0)
            authority.put_artifact("T-RO", "RiskAssessment", "codeops-triage", {"risk": "low"}, [], 1)
            authority.transition("T-RO", "TRIAGED", "codeops-triage", "triaged", 1)
            authority.put_artifact("T-RO", "EnvironmentSnapshot", "codeops-env-bootstrap", {"base": "snapshot"}, [], 2)
            authority.transition("T-RO", "BOOTSTRAPPED", "codeops-env-bootstrap", "ready", 2)
            authority.put_artifact("T-RO", "RootCauseHypotheses", "codeops-repo-analyst", {"hypotheses": ["h1"]}, [], 3)
            authority.transition("T-RO", "LOCATED", "codeops-repo-analyst", "located", 3)

            # Read-only branch: no PatchBundle is ever produced.
            with self.assertRaises(AuthorityError):
                authority.put_artifact(
                    "T-RO",
                    "VerificationReport",
                    "codeops-verifier",
                    {"verdict": "PASS", "commands": ["pytest"], "verifier_context": {"workspace": "isolated"}},
                    [],
                    4,
                )
            authority.transition("T-RO", "READONLY_VERIFYING", "codeops-verifier", "independent read-only verification", 4)

            with self.assertRaises(AuthorizationError):
                authority.transition("T-RO", "READONLY_VERIFIED", "codeops-verifier", "no report yet", 5)
            with self.assertRaises(AuthorityError):
                authority.put_artifact(
                    "T-RO",
                    "VerificationReport",
                    "codeops-verifier",
                    {"verdict": "PASS", "commands": ["pytest"]},
                    [],
                    5,
                )
            authority.put_artifact(
                "T-RO",
                "VerificationReport",
                "codeops-verifier",
                {"verdict": "PASS", "commands": ["pytest"], "verifier_context": {"workspace": "isolated"}},
                [],
                5,
            )
            authority.transition("T-RO", "READONLY_VERIFIED", "codeops-verifier", "report verified", 5)

            # EVIDENCE_PACKED runs the full evidence-pack validation as a gate.
            packed = authority.transition("T-RO", "EVIDENCE_PACKED", "codeops-lead", "evidence pack validated", 6)
            self.assertEqual(packed["state"], "EVIDENCE_PACKED")
            pack = authority.evidence_pack("T-RO", validate=True)
            self.assertTrue(pack["validation"]["valid"], pack["validation"]["errors"])
            closed = authority.transition("T-RO", "CLOSED", "codeops-lead", "closed after evidence pack", 7)
            self.assertEqual(closed["state"], "CLOSED")

    def test_release_ready_requires_passing_independent_report(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-GATE", "software-engineering", {"issue": "timeout"}, "trace-gate")
            authority.transition("T-GATE", "FUSED", "codeops-intake", "fused", 0)
            authority.transition("T-GATE", "TRIAGED", "codeops-triage", "triaged", 1)
            authority.transition("T-GATE", "BOOTSTRAPPED", "codeops-env-bootstrap", "ready", 2)
            authority.transition("T-GATE", "LOCATED", "codeops-repo-analyst", "located", 3)
            authority.transition("T-GATE", "PLANNED", "codeops-plan", "planned", 4)
            approval = authority.request_approval("T-GATE", "codeops-plan", {"files": ["src/retry_guard.py"]}, "AWAITING_APPROVAL", 5)
            authority.transition("T-GATE", "AWAITING_APPROVAL", "codeops-plan", "approval requested", 5)
            authority.decide_approval(approval["approval_id"], "reviewer", "APPROVED", approval["scope_digest"], "!room:local", "$event")
            authority.put_artifact(
                "T-GATE",
                "PatchBundle",
                "codeops-executor",
                {"approval_id": approval["approval_id"], "changed_files": ["src/retry_guard.py"], "diff_digest": "sha256:test"},
                [],
                6,
            )
            authority.transition("T-GATE", "PATCHED", "codeops-executor", "patched", 6)
            authority.transition("T-GATE", "VERIFYING", "codeops-verifier", "verifying", 7)

            # No VerificationReport at the current version: denied.
            with self.assertRaises(AuthorizationError):
                authority.transition("T-GATE", "RELEASE_READY", "codeops-verifier", "no report", 8)
            # A FAIL verdict must not unlock RELEASE_READY.
            authority.put_artifact(
                "T-GATE",
                "VerificationReport",
                "codeops-verifier",
                {"verdict": "FAIL", "commands": ["pytest"], "verifier_context": {"workspace": "isolated"}, "failure_signature": "REGRESSION_TIMEOUT_GUARD"},
                [],
                8,
            )
            with self.assertRaises(AuthorizationError):
                authority.transition("T-GATE", "RELEASE_READY", "codeops-verifier", "failed verdict", 8)
            # A PASS verdict from the independent verifier unlocks the gate.
            authority.put_artifact(
                "T-GATE",
                "VerificationReport",
                "codeops-verifier",
                {"verdict": "PASS", "commands": ["pytest"], "verifier_context": {"workspace": "isolated"}},
                [],
                8,
            )
            released = authority.transition("T-GATE", "RELEASE_READY", "codeops-verifier", "independent verification passed", 8)
            self.assertEqual(released["state"], "RELEASE_READY")

    def test_leader_cannot_own_domain_states_but_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            authority.create_task("T-LEAD", "software-engineering", {"issue": "x"}, "trace-lead")
            with self.assertRaises(AuthorizationError):
                authority.transition("T-LEAD", "FUSED", "codeops-lead", "leader must not fabricate domain progress", 0)
            authority.transition("T-LEAD", "FUSED", "codeops-intake", "fused", 0)
            authority.transition("T-LEAD", "TRIAGED", "codeops-triage", "triaged", 1)
            recovering = authority.transition("T-LEAD", "RECOVERING", "codeops-lead", "leader initiates recovery", 2)
            self.assertEqual(recovering["state"], "RECOVERING")
            needs_human = authority.transition("T-LEAD", "NEEDS_HUMAN", "codeops-lead", "escalate", 3)
            self.assertEqual(needs_human["state"], "NEEDS_HUMAN")


if __name__ == "__main__":
    unittest.main()
