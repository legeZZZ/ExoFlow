import json
import tempfile
import unittest
from pathlib import Path

from exoflow.native_mcp import (
    AuthorityError,
    AuthorizationError,
    SQLiteStateAuthority,
)
from exoflow.skill_distill import (
    DistillError,
    SkillPatch,
    TracePool,
    build_candidate,
    distill,
    evaluate_candidate,
    merge_patches,
    propose_failure_patches,
    propose_success_patches,
    publish,
    record_human_review,
    rollback,
    scan_license,
    scan_sensitive,
    validate_skill_document,
)


def _pack(task_id, verdict=None, signature=None, domain="software-engineering", state="CLOSED"):
    artifacts = [
        {
            "artifact_type": "IssueCluster",
            "payload": {"issues": ["timeout-budget"]},
        }
    ]
    if verdict:
        artifacts.append(
            {
                "artifact_type": "VerificationReport",
                "payload": {
                    "verdict": verdict,
                    "commands": ["python3 -m unittest"],
                    "verifier_context": {"workspace": "isolated"},
                    **({"failure_signature": signature} if signature else {}),
                },
            }
        )
    return {
        "task": {"task_id": task_id, "domain": domain, "state": state, "state_version": 8},
        "events": [
            {"event_type": "ARTIFACT_PUBLISHED", "artifact_type": "IssueCluster"},
            {"event_type": "STATE_TRANSITION", "payload": {"to": state}},
        ],
        "artifacts": artifacts,
    }


BASE_SKILL_DOC = "# verifier skill\n\n## 职责\n独立验证。\n\n## 流程\n重跑测试。\n\n## 硬规则\n禁止引用他人结论。\n"


class TracePoolTests(unittest.TestCase):
    def test_ingest_tags_by_verdict_and_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            record = pool.ingest(_pack("T1", verdict="FAIL", signature="SIG_TIMEOUT"))
            self.assertEqual(record["tags"]["verdict"], "FAIL")
            self.assertEqual(record["tags"]["failure_signatures"], ["SIG_TIMEOUT"])
            pool.ingest(_pack("T2", verdict="PASS"))
            self.assertEqual(len(pool.list()), 2)
            self.assertEqual(len(pool.by_domain("software-engineering")), 2)
            self.assertEqual(pool.by_domain("other"), [])

    def test_ingest_requires_task_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DistillError):
                TracePool(directory).ingest({"task": {}})


class PatchProposalTests(unittest.TestCase):
    def test_success_patterns_from_pass_traces(self):
        records = [
            TracePool.__new__(TracePool) and None or None,
        ]
        records = []
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            pool.ingest(_pack("T1", verdict="PASS"))
            pool.ingest(_pack("T2", verdict="PASS"))
            records = pool.list()
        patches = propose_success_patches(records, "verifier")
        self.assertTrue(patches)
        self.assertTrue(all(p.kind == "pattern" for p in patches))
        self.assertTrue(all(p.target_skill == "verifier" for p in patches))

    def test_failure_guards_from_signatures(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            pool.ingest(_pack("T1", verdict="FAIL", signature="SIG_A"))
            pool.ingest(_pack("T2", verdict="FAIL", signature="SIG_A"))
            records = pool.list()
        patches = propose_failure_patches(records, "verifier")
        self.assertTrue(any(p.kind == "guard" and "SIG_A" in p.content for p in patches))
        guard = [p for p in patches if "SIG_A" in p.content][0]
        self.assertIn("T1", guard.source_traces)
        self.assertIn("T2", guard.source_traces)

    def test_pass_only_pool_yields_no_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            pool.ingest(_pack("T1", verdict="PASS"))
            records = pool.list()
        self.assertEqual(propose_failure_patches(records, "verifier"), [])


class MergeTests(unittest.TestCase):
    def test_merge_appends_under_sections(self):
        patches = [
            SkillPatch("verifier", "pattern", "独立验证先行", "内容A", ("T1",)),
            SkillPatch("verifier", "guard", "防错：SIG_A", "内容B", ("T2",)),
        ]
        merged, conflicts = merge_patches(BASE_SKILL_DOC, patches)
        self.assertEqual(conflicts, [])
        self.assertIn("独立验证先行", merged.split("## 流程")[1].split("## 硬规则")[0])
        self.assertIn("防错：SIG_A", merged.split("## 硬规则")[1])

    def test_duplicate_titles_conflict(self):
        patches = [
            SkillPatch("verifier", "pattern", "X", "a", ("T1",)),
            SkillPatch("verifier", "pattern", "X", "b", ("T2",)),
        ]
        _, conflicts = merge_patches(BASE_SKILL_DOC, patches)
        self.assertTrue(any(c.startswith("DUPLICATE_PATCH") for c in conflicts))

    def test_pattern_guard_contradiction_conflict(self):
        title = "防错：超时预算"
        patches = [
            SkillPatch("verifier", "guard", title, "停", ("T1",)),
            SkillPatch("verifier", "pattern", "超时预算", "做", ("T2",)),
        ]
        _, conflicts = merge_patches(BASE_SKILL_DOC, patches)
        self.assertTrue(any(c.startswith("CONTRADICTORY_PATCH") for c in conflicts))

    def test_missing_sections_flagged(self):
        errors = validate_skill_document("# 空文档\n")
        self.assertEqual(len(errors), 3)


class ScanAndEvaluationTests(unittest.TestCase):
    def test_sensitive_and_license_scans(self):
        self.assertTrue(scan_sensitive("token: bearer abcdefghijklmnopqrstuvwxyz123456"))
        self.assertTrue(scan_sensitive("-----BEGIN RSA PRIVATE KEY-----"))
        self.assertEqual(scan_sensitive("clean text"), [])
        self.assertTrue(scan_license("GPL-3 licensed"))
        self.assertEqual(scan_license("Apache-2.0"), [])

    def test_evaluation_gates(self):
        patch = SkillPatch("verifier", "pattern", "独立验证先行", "内容", ("T1",))
        merged, _ = merge_patches(BASE_SKILL_DOC, [patch])
        candidate = build_candidate("verifier", [patch], merged, ["T1"])
        evaluated = evaluate_candidate(candidate)
        self.assertEqual(evaluated["review_status"], "evaluation_passed")
        self.assertTrue(all(v["pass"] for v in evaluated["evaluations"].values()))

    def test_review_requires_passed_evaluation(self):
        candidate = build_candidate("verifier", [], BASE_SKILL_DOC, ["T1"])
        evaluated = evaluate_candidate(candidate)
        self.assertEqual(evaluated["review_status"], "evaluation_failed")
        with self.assertRaises(DistillError):
            record_human_review(evaluated, True, "reviewer")


class PublishTests(unittest.TestCase):
    def _approved_candidate(self):
        patch = SkillPatch("verifier", "pattern", "独立验证先行", "内容", ("T1",))
        merged, _ = merge_patches(BASE_SKILL_DOC, [patch])
        candidate = build_candidate("verifier", [patch], merged, ["T1"])
        evaluated = evaluate_candidate(candidate)
        return record_human_review(evaluated, True, "reviewer", "ok")

    def test_publish_increments_version_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            matrix_path = Path(directory) / "skill-matrix.json"
            matrix = publish(matrix_path, self._approved_candidate())
            self.assertEqual(matrix["skills"]["verifier"]["current_version"], 1)
            matrix = publish(matrix_path, self._approved_candidate())
            self.assertEqual(matrix["skills"]["verifier"]["current_version"], 2)
            matrix = rollback(matrix_path, "verifier", 1)
            self.assertEqual(matrix["skills"]["verifier"]["current_version"], 1)
            self.assertEqual(len(matrix["skills"]["verifier"]["rollbacks"]), 1)

    def test_publish_rejects_unapproved(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_candidate("verifier", [], BASE_SKILL_DOC, ["T1"])
            with self.assertRaises(DistillError):
                publish(Path(directory) / "m.json", candidate)


class EndToEndTests(unittest.TestCase):
    def test_distill_pipeline_produces_evaluated_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            pool.ingest(_pack("T1", verdict="PASS"))
            pool.ingest(_pack("T2", verdict="FAIL", signature="SIG_TIMEOUT"))
            candidate = distill(pool, "verifier", BASE_SKILL_DOC)
        self.assertEqual(candidate["review_status"], "evaluation_passed")
        self.assertTrue(candidate["patches"])
        self.assertTrue(candidate["scan"]["pass"])
        self.assertEqual(candidate["consolidation_conflicts"], [])

    def test_distill_blocks_on_sensitive_content(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = TracePool(directory)
            pool.ingest(_pack("T1", verdict="PASS"))
            candidate = distill(
                pool,
                "verifier",
                BASE_SKILL_DOC + "\n参考: bearer abcdefghijklmnopqrstuvwxyz123456\n",
            )
        self.assertEqual(candidate["review_status"], "blocked")
        self.assertFalse(candidate["scan"]["pass"])


class AuthorityGateTests(unittest.TestCase):
    """SKILL_DISTILLING -> CLOSED requires an approved SkillCandidate or an
    explicit NO_DISTILL_CONFIRMED marker from the lead."""

    def _drive_to_distilling(self, authority, task_id):
        authority.create_task(task_id, "software-engineering", {"issue": "timeout"}, "trace-m1")
        authority.transition(task_id, "FUSED", "codeops-intake", "fused", 0)
        authority.transition(task_id, "TRIAGED", "codeops-triage", "triaged", 1)
        authority.transition(task_id, "BOOTSTRAPPED", "codeops-env-bootstrap", "ready", 2)
        authority.transition(task_id, "LOCATED", "codeops-repo-analyst", "located", 3)
        authority.transition(task_id, "PLANNED", "codeops-plan", "planned", 4)
        approval = authority.request_approval(task_id, "codeops-plan", {"files": ["src/retry_guard.py"]}, "AWAITING_APPROVAL", 5)
        authority.transition(task_id, "AWAITING_APPROVAL", "codeops-plan", "approval requested", 5)
        authority.decide_approval(approval["approval_id"], "reviewer", "APPROVED", approval["scope_digest"], "!room:local", "$event")
        authority.put_artifact(
            task_id,
            "PatchBundle",
            "codeops-executor",
            {"approval_id": approval["approval_id"], "changed_files": ["src/retry_guard.py"], "diff_digest": "sha256:test"},
            [],
            6,
        )
        authority.transition(task_id, "PATCHED", "codeops-executor", "patched", 6)
        authority.transition(task_id, "VERIFYING", "codeops-verifier", "verifying", 7)
        authority.put_artifact(
            task_id,
            "VerificationReport",
            "codeops-verifier",
            {"verdict": "PASS", "commands": ["pytest"], "verifier_context": {"workspace": "isolated"}},
            [],
            8,
        )
        authority.transition(task_id, "RELEASE_READY", "codeops-verifier", "verified", 8)
        authority.transition(task_id, "POSTMORTEM", "codeops-postmortem", "postmortem", 9)
        authority.transition(task_id, "SKILL_DISTILLING", "codeops-postmortem", "distilling", 10)
        return 11

    def test_close_blocked_without_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_distilling(authority, "T-M1")
            with self.assertRaises(AuthorizationError):
                authority.transition("T-M1", "CLOSED", "codeops-lead", "nothing distilled", version)

    def test_close_allowed_with_no_distill_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_distilling(authority, "T-M1B")
            closed = authority.transition("T-M1B", "CLOSED", "codeops-lead", "NO_DISTILL_CONFIRMED: analysis-only task", version)
            self.assertEqual(closed["state"], "CLOSED")

    def test_close_allowed_with_approved_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_distilling(authority, "T-M1C")
            # Draft candidate does not open the gate.
            authority.put_artifact(
                "T-M1C",
                "SkillCandidate",
                "codeops-postmortem",
                {"target_skill": "verifier", "patches": [], "review_status": "draft"},
                [],
                version,
            )
            with self.assertRaises(AuthorizationError):
                authority.transition("T-M1C", "CLOSED", "codeops-lead", "draft candidate", version)
            # Approved candidate opens the gate.
            authority.put_artifact(
                "T-M1C",
                "SkillCandidate",
                "codeops-postmortem",
                {"target_skill": "verifier", "patches": [{"title": "独立验证先行"}], "review_status": "approved"},
                [],
                version,
            )
            closed = authority.transition("T-M1C", "CLOSED", "codeops-lead", "skill candidate approved and published", version)
            self.assertEqual(closed["state"], "CLOSED")

    def test_candidate_payload_fields_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = SQLiteStateAuthority(Path(directory) / "state.sqlite3")
            version = self._drive_to_distilling(authority, "T-M1D")
            with self.assertRaises(AuthorityError):
                authority.put_artifact(
                    "T-M1D",
                    "SkillCandidate",
                    "codeops-postmortem",
                    {"patches": []},
                    [],
                    version,
                )


if __name__ == "__main__":
    unittest.main()
