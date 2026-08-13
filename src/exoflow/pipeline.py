"""ExoFlow incident-fix pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .foundation import (
    AgentIdentity,
    AgentTeamsControlPlane,
    ci_port_for,
    LocalEvidenceProvider,
    SQLiteCheckpointProvider,
    PORT_MANIFESTS,
    TeamTopology,
    provider_by_id,
)


PIPELINE_AGENTS = [
    ("intake", "Issue intake and fusion", ["RECEIVED", "FUSED"], ["cluster issues", "deduplicate reports"], ["IssueCluster"], ["IssueFusion"]),
    ("triage", "Risk and priority triage", ["TRIAGED"], ["assess risk", "set action level"], ["RiskAssessment"], ["RiskGuard", "PolicyCheck"]),
    ("env_bootstrap", "Reproducible environment bootstrap", ["BOOTSTRAPPED"], ["prepare isolated workspace", "capture baseline"], ["EnvironmentSnapshot"], ["ResumeGuard"]),
    ("repo_analyst", "Repository and root-cause analysis", ["LOCATED"], ["map repository", "propose hypotheses"], ["RootCauseHypotheses"], ["RepoMap", "RootCauseProbe", "RunbookRAG", "IncidentMemory"]),
    ("plan", "Change planning", ["PLANNED", "AWAITING_APPROVAL"], ["draft bounded change plans", "define rollback"], ["ChangePlan"], ["PolicyCheck", "JudgeCalibrator"]),
    ("executor", "Approved patch execution", ["PATCHED", "RECOVERING"], ["execute approved diff", "record side effects"], ["PatchBundle"], ["SafePatchExec", "ResumeGuard", "RiskGuard"]),
    ("verifier", "Independent verification", ["VERIFYING", "RELEASE_READY", "NEEDS_HUMAN"], ["run hidden checks", "emit failure signature"], ["VerificationReport"], ["VerifyAndReplay", "JudgeCalibrator", "PolicyCheck"]),
    ("postmortem", "Postmortem and skill distillation", ["POSTMORTEM", "SKILL_DISTILLING", "CLOSED"], ["summarize trace", "propose versioned skill"], ["SkillCandidate"], ["IncidentMemory", "SkillDistiller", "JudgeCalibrator"]),
]


PIPELINE_SKILLS = [
    ("IssueFusion", "diagnostic", "deterministic+retrieval"),
    ("RepoMap", "diagnostic", "tool"),
    ("RootCauseProbe", "diagnostic", "tool+model"),
    ("RunbookRAG", "knowledge", "retrieval"),
    ("IncidentMemory", "knowledge", "retrieval"),
    ("SkillDistiller", "knowledge", "model+policy"),
    ("RiskGuard", "governance", "deterministic"),
    ("PolicyCheck", "governance", "deterministic"),
    ("JudgeCalibrator", "governance", "calibrated-model"),
    ("SafePatchExec", "execution", "provider"),
    ("VerifyAndReplay", "execution", "tool"),
    ("ResumeGuard", "execution", "deterministic"),
]


def build_control_plane() -> AgentTeamsControlPlane:
    control_plane = AgentTeamsControlPlane()
    for agent_id, role, states, capabilities, can_write, can_call in PIPELINE_AGENTS:
        control_plane.register_agent(AgentIdentity(agent_id, role, states, capabilities, can_write, can_call))
    for skill_id, category, executor in PIPELINE_SKILLS:
        control_plane.register_skill(skill_id, {"skill_id": skill_id, "version": "0.1.0", "category": category, "executor": executor, "schema_version": "1.0", "policy": {"requires_trace": True, "requires_evidence": True}})
    control_plane.register_topology(TeamTopology("exoflow", "AgentTeamsControlPlane", list(control_plane.agents.keys()), [
        {"from": "intake", "to": "triage", "mode": "sequential"},
        {"from": "triage", "to": "env_bootstrap", "mode": "sequential"},
        {"from": "env_bootstrap", "to": "repo_analyst", "mode": "sequential"},
        {"from": "repo_analyst", "to": "plan", "mode": "fan-in", "input": "two_root_cause_hypotheses"},
        {"from": "plan", "to": "executor", "mode": "approval-gated"},
        {"from": "executor", "to": "verifier", "mode": "sequential"},
        {"from": "verifier", "to": "executor", "mode": "bounded-repair", "condition": "failure_signature"},
        {"from": "verifier", "to": "postmortem", "mode": "sequential"},
    ], {"fan_out": ["repo_analyst -> hypothesis_1, hypothesis_2", "plan -> plan_1, plan_2, plan_3"], "fan_in": "plan ranks hypotheses and produces a bounded ChangePlan", "conflict_policy": "evidence-backed ranking; unresolved conflict goes to human"}))
    return control_plane


def _checkpoint(control_plane: AgentTeamsControlPlane, checkpoint: SQLiteCheckpointProvider, task_id: str) -> None:
    task = control_plane.tasks[task_id]
    checkpoint.save(task_id, task.state_version, control_plane.checkpoint_payload(task_id))


def run_demo(base_dir: Path, provider_id: str = "opencode", fail_first: bool = True, input_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    control_plane = build_control_plane()
    checkpoint = SQLiteCheckpointProvider(base_dir / "checkpoints" / "exoflow.sqlite3")
    evidence_provider = LocalEvidenceProvider(base_dir / "evidence")
    package_fixture_root = Path(__file__).resolve().parent / "fixtures" / "demo-service"
    source_fixture_root = Path(__file__).resolve().parents[2] / "fixtures" / "demo-service"
    fixture_root = package_fixture_root if package_fixture_root.is_dir() else source_fixture_root
    provider = provider_by_id(
        provider_id,
        fail_first=fail_first,
        workspace_root=base_dir / "workspaces",
        fixture_root=fixture_root,
    )
    ci_port = ci_port_for(provider, fail_first=fail_first)
    task_input = dict(input_payload or {"source": "ci+user-feedback", "symptom": "request timeout after retry", "repository": "demo-service", "risk": "low"})
    task_id = str(task_input.pop("task_id", "T1-exoflow-demo"))
    task = control_plane.create_task(task_id, "software-engineering", task_input)

    def move(target: str, actor: str, reason: str, metadata: Dict[str, Any] = None) -> None:
        expected_version = control_plane.tasks[task_id].state_version
        control_plane.transition(task_id, target, actor, reason, metadata, expected_state_version=expected_version)
        _checkpoint(control_plane, checkpoint, task_id)

    def evidence(kind: str, label: str, source: str, content: Any) -> str:
        return control_plane.record_evidence(task_id, kind, label, source, content).evidence_id

    input_ev = evidence("input", "CI regression and user report", "intake", task.input_payload)
    move("FUSED", "intake", "two reports describe the same timeout signature", {"evidence_ref": input_ev})
    issue = control_plane.publish_artifact(task_id, "IssueCluster", "intake", {"canonical_symptom": "request timeout after retry", "sources": ["ci", "user-feedback"], "duplicate_count": 1}, [input_ev])
    move("TRIAGED", "triage", "low blast radius and bounded repository scope")
    risk = control_plane.publish_artifact(task_id, "RiskAssessment", "triage", {"risk_level": "low", "action_level": "sandbox-only", "approval_required": True}, [])
    move("BOOTSTRAPPED", "env_bootstrap", "isolated fixture and baseline tests are available")
    env = control_plane.publish_artifact(task_id, "EnvironmentSnapshot", "env_bootstrap", {"workspace": "isolated/demo-service", "baseline": "public-tests-pass", "dependencies": ["python>=3.9"], "snapshot_id": "ws_demo_v1"}, [])
    move("LOCATED", "repo_analyst", "two independent hypotheses share a bounded retry guard")
    roots = control_plane.publish_artifact(task_id, "RootCauseHypotheses", "repo_analyst", {"hypotheses": [{"id": "H1", "statement": "retry timeout is not carried into the second attempt", "supporting_evidence": ["call-chain", "failure-signature"]}, {"id": "H2", "statement": "retry path creates a duplicate side effect", "supporting_evidence": ["idempotency-audit"]}], "selected": "H1"}, [])
    move("PLANNED", "plan", "bounded patch with a rollback and hidden regression check")
    approved_scope = ["src/retry_guard.py", "tests/test_public.py"] if provider_id == "fixture-local" else ["retry_guard.py", "tests/test_retry_guard.py"]
    plan = control_plane.publish_artifact(task_id, "ChangePlan", "plan", {"plans": [{"id": "P1", "change": "carry timeout budget", "rollback": "revert patch", "risk": "low"}, {"id": "P2", "change": "add idempotent retry guard", "rollback": "disable guard", "risk": "medium"}, {"id": "P3", "change": "remove retry", "rollback": "restore retry", "risk": "high"}], "recommended": "P1+P2", "approved_scope": approved_scope}, [])
    approval_id = control_plane.request_approval(task_id, "plan", {"files": approved_scope, "commands": ["python3 -m unittest discover -s tests -v", "python3 -m unittest discover -s hidden_tests -v"]}, expected_state="AWAITING_APPROVAL")
    move("AWAITING_APPROVAL", "plan", "high-impact actions require a bounded human approval", {"approval_id": approval_id})
    approval = control_plane.approve(approval_id, "human-reviewer", "APPROVED", "approved files and test command only")
    move("PATCHED", "executor", "approval scope accepted", {"approval_id": approval_id})

    attempts: List[Dict[str, Any]] = []
    verification_results: List[Dict[str, Any]] = []
    for attempt in (1, 2):
        execution = provider.execute({"task_id": task_id, "workspace_id": task_id, "attempt": attempt, "prompt": "Fix the bounded retry timeout issue in demo-service.", "approved_scope": approved_scope})
        attempts.append(execution)
        execution_ev = evidence("execution", "provider execution attempt %d" % attempt, provider.provider_id, execution)
        control_plane.publish_artifact(task_id, "PatchBundle", "executor", {"attempt": attempt, "provider": provider.provider_id, "patch": execution.get("patch"), "status": execution.get("status")}, [execution_ev])
        move("VERIFYING", "verifier", "patch attempt %d is ready for independent verification" % attempt, {"attempt": attempt})
        verification = ci_port.run({
            "task_id": task_id,
            "attempt": attempt,
            "workspace": execution.get("workspace", ""),
            "verifier_workspace": execution.get("verifier_workspace", ""),
            "public_suite": "tests",
            "hidden_suite": "hidden_tests",
        })
        verification_results.append(verification)
        verification_ev = evidence("verification", "independent hidden verification attempt %d" % attempt, "verifier", verification)
        control_plane.publish_artifact(task_id, "VerificationReport", "verifier", {"attempt": attempt, "provider": verification.get("provider"), "public": verification.get("public"), "hidden": verification.get("hidden"), "failure_signature": verification.get("failure_signature"), "verifier_context": "artifact+spec+independent-test"}, [verification_ev])
        if verification.get("hidden") == "pass":
            break
        move("PATCHED", "executor", "verifier failure signature requires bounded repair", {"failure_signature": verification.get("failure_signature"), "attempt": attempt})

    final_verification = verification_results[-1]
    if final_verification.get("hidden") != "pass":
        move("NEEDS_HUMAN", "verifier", "same failure signature remains after bounded retries")
    else:
        move("RELEASE_READY", "verifier", "public and hidden checks pass")
        move("POSTMORTEM", "postmortem", "successful and failed attempts are retained for review")
        postmortem_ev = evidence("postmortem", "trace review and failure signature", "postmortem", {"attempts": attempts, "reuse_candidate": "idempotent-retry-guard", "review": "human review required before skill publication"})
        control_plane.publish_artifact(task_id, "SkillCandidate", "postmortem", {"skill_id": "idempotent-retry-guard", "trigger": "REGRESSION_TIMEOUT_GUARD", "steps": ["carry timeout budget", "check idempotency key", "run hidden regression"], "negative_examples": ["do not broaden approved files"], "status": "PENDING_REVIEW"}, [postmortem_ev])
        move("SKILL_DISTILLING", "postmortem", "candidate passed trace completeness checks")
        move("CLOSED", "postmortem", "demo closed with evidence pack")

    pack = control_plane.evidence_pack(task_id)
    pack.update({"pipeline": "incident-fix", "provider": provider.provider_id, "agents": list(control_plane.agents.keys()), "skills": list(control_plane.skills.keys()), "port_manifests": PORT_MANIFESTS, "provider_status": "local-provider", "checkpoint": checkpoint.load(task_id), "topologies": pack["topologies"], "summary": {"final_state": control_plane.tasks[task_id].state, "attempts": len(attempts), "hidden_verification": final_verification.get("hidden"), "execution_mode": attempts[-1].get("mode"), "workspace": attempts[-1].get("workspace"), "changed_files": attempts[-1].get("changed_files", []), "issue_artifact": issue.artifact_id, "environment_artifact": env.artifact_id, "root_cause_artifact": roots.artifact_id, "plan_artifact": plan.artifact_id, "risk_artifact": risk.artifact_id}})
    pack_path = evidence_provider.write_pack(task_id, pack)
    pack["evidence_pack_path"] = str(pack_path)
    return pack


def replay_provider(provider_id: str, base_dir: Path) -> Dict[str, Any]:
    """Run the same deterministic task through a second Provider contract."""
    result = run_demo(base_dir, provider_id=provider_id, fail_first=True)
    return {"provider": provider_id, "task_fixture": "T1-exoflow-demo-v1", "final_state": result["summary"]["final_state"], "hidden_verification": result["summary"]["hidden_verification"], "evidence_schema": "1.0", "trace_event_count": len(result["trace"])}
