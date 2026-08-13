"""Single source of truth for the ExoFlow task state machine.

Every consumer — the local conformance control plane (foundation.py), the
native SQLite state authority (native_mcp.py) and the dependency-free Worker
package oracle (packages/team-leader/scripts/state_machine.py) — must derive
from these definitions. The Worker package cannot import this module, so a
conformance test (tests/test_state_machine_conformance.py) pins the embedded
copy to this file.

Standard path:

    RECEIVED -> FUSED -> TRIAGED -> BOOTSTRAPPED -> LOCATED -> PLANNED
      -> AWAITING_APPROVAL -> PATCHED -> VERIFYING -> RELEASE_READY
      -> POSTMORTEM -> SKILL_DISTILLING -> CLOSED

Read-only analysis branch (no PatchBundle is ever produced):

    LOCATED -> READONLY_VERIFYING -> READONLY_VERIFIED -> EVIDENCE_PACKED -> CLOSED
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple


# --- Software engineering task states -----------------------------------------

TRANSITIONS: Dict[str, Set[str]] = {
    "RECEIVED": {"FUSED", "RECOVERING"},
    "FUSED": {"TRIAGED", "RECOVERING"},
    "TRIAGED": {"BOOTSTRAPPED", "NEEDS_HUMAN", "RECOVERING"},
    "BOOTSTRAPPED": {"LOCATED", "RETRYABLE_FAILURE", "NEEDS_HUMAN", "RECOVERING"},
    "LOCATED": {"PLANNED", "READONLY_VERIFYING", "NEEDS_HUMAN", "RECOVERING"},
    "PLANNED": {"AWAITING_APPROVAL", "BLOCKED_BY_POLICY", "NEEDS_HUMAN", "RECOVERING"},
    "AWAITING_APPROVAL": {"PATCHED", "NEEDS_HUMAN", "BLOCKED_BY_POLICY", "RECOVERING"},
    "PATCHED": {"VERIFYING", "NEEDS_HUMAN", "RECOVERING"},
    "VERIFYING": {"RELEASE_READY", "PATCHED", "NEEDS_HUMAN", "RECOVERING"},
    "RELEASE_READY": {"POSTMORTEM", "CLOSED", "RECOVERING"},
    "POSTMORTEM": {"SKILL_DISTILLING", "CLOSED", "RECOVERING"},
    "SKILL_DISTILLING": {"CLOSED", "NEEDS_HUMAN", "RECOVERING"},
    # Read-only analysis branch.
    "READONLY_VERIFYING": {"READONLY_VERIFIED", "NEEDS_HUMAN", "RECOVERING"},
    "READONLY_VERIFIED": {"EVIDENCE_PACKED", "NEEDS_HUMAN", "RECOVERING"},
    "EVIDENCE_PACKED": {"CLOSED"},
    # Shared terminal / exception states.
    "NEEDS_HUMAN": {"TRIAGED", "LOCATED", "PLANNED", "READONLY_VERIFYING", "CLOSED", "RECOVERING"},
    "RECOVERING": {"TRIAGED", "BOOTSTRAPPED", "LOCATED", "PLANNED", "PATCHED", "VERIFYING", "READONLY_VERIFYING", "CLOSED", "NEEDS_HUMAN"},
    "RETRYABLE_FAILURE": {"BOOTSTRAPPED", "PATCHED", "NEEDS_HUMAN", "RECOVERING"},
    "BLOCKED_BY_POLICY": {"NEEDS_HUMAN", "CLOSED", "RECOVERING"},
    "CLOSED": set(),
}

# --- Actor ownership ----------------------------------------------------------

# States a Worker (or the Leader) may move a task INTO. Domain Workers only own
# their own stage outputs; the Leader owns coordination and recovery targets
# but never owns domain stage states — it cannot fabricate domain progress.
ACTOR_TARGETS: Dict[str, Set[str]] = {
    "codeops-intake": {"FUSED"},
    "codeops-triage": {"TRIAGED"},
    "codeops-env-bootstrap": {"BOOTSTRAPPED"},
    "codeops-repo-analyst": {"LOCATED"},
    "codeops-plan": {"PLANNED", "AWAITING_APPROVAL"},
    "codeops-executor": {"PATCHED", "RECOVERING"},
    "codeops-verifier": {"VERIFYING", "RELEASE_READY", "READONLY_VERIFYING", "READONLY_VERIFIED", "NEEDS_HUMAN"},
    "codeops-postmortem": {"POSTMORTEM", "SKILL_DISTILLING", "CLOSED"},
    "codeops-lead": {"RECOVERING", "NEEDS_HUMAN", "EVIDENCE_PACKED", "CLOSED"},
}

# --- Artifact ownership and lifecycle -----------------------------------------

ARTIFACT_PRODUCERS: Dict[str, str] = {
    "IssueCluster": "codeops-intake",
    "RiskAssessment": "codeops-triage",
    "EnvironmentSnapshot": "codeops-env-bootstrap",
    "RootCauseHypotheses": "codeops-repo-analyst",
    "ChangePlan": "codeops-plan",
    "PatchBundle": "codeops-executor",
    "VerificationReport": "codeops-verifier",
    "Postmortem": "codeops-postmortem",
    "SkillCandidate": "codeops-postmortem",
}

# An artifact type may only be written while the task is in one of these
# states. This stops e.g. a Verifier from publishing a VerificationReport
# before the task has actually entered a verification state.
ARTIFACT_ALLOWED_STATES: Dict[str, Set[str]] = {
    "IssueCluster": {"RECEIVED", "FUSED"},
    "RiskAssessment": {"FUSED", "TRIAGED"},
    "EnvironmentSnapshot": {"TRIAGED", "BOOTSTRAPPED"},
    "RootCauseHypotheses": {"BOOTSTRAPPED", "LOCATED"},
    "ChangePlan": {"LOCATED", "PLANNED", "AWAITING_APPROVAL"},
    "PatchBundle": {"AWAITING_APPROVAL"},
    "VerificationReport": {"VERIFYING", "READONLY_VERIFYING"},
    "Postmortem": {"RELEASE_READY", "READONLY_VERIFIED", "POSTMORTEM"},
    "SkillCandidate": {"POSTMORTEM", "SKILL_DISTILLING"},
}

# Minimal required payload fields per artifact type (structural schema gate at
# the authority boundary; full schema validation remains a Skill concern).
ARTIFACT_REQUIRED_FIELDS: Dict[str, Tuple[str, ...]] = {
    "PatchBundle": ("approval_id", "changed_files"),
    "VerificationReport": ("verdict", "commands", "verifier_context"),
    "SkillCandidate": ("target_skill", "patches", "review_status"),
}

# Transition preconditions expressed as (from_state, to_state) ->
# (required_artifact_type, must_match_current_version). Enforced by the native
# authority; see native_mcp.py.
# - PatchBundle is written during AWAITING_APPROVAL (one version before
#   PATCHED), so PATCHED -> VERIFYING only requires its existence.
# - Verification gates require a VerificationReport written at the current
#   version, i.e. inside the active verification state.
TRANSITION_REQUIRED_ARTIFACTS: Dict[Tuple[str, str], Tuple[str, bool]] = {
    ("PATCHED", "VERIFYING"): ("PatchBundle", False),
    ("VERIFYING", "RELEASE_READY"): ("VerificationReport", True),
    ("READONLY_VERIFYING", "READONLY_VERIFIED"): ("VerificationReport", True),
}

# Targets that additionally require a passing verification verdict.
TRANSITION_REQUIRED_VERDICT: Dict[Tuple[str, str], str] = {
    ("VERIFYING", "RELEASE_READY"): "PASS",
    ("READONLY_VERIFYING", "READONLY_VERIFIED"): "PASS",
}

# The read-only branch: EVIDENCE_PACKED may only be entered after the exported
# evidence pack passes validation inside the authority (see native_mcp.py).
EVIDENCE_PACKED_PRECONDITION: Tuple[str, str] = ("READONLY_VERIFIED", "EVIDENCE_PACKED")

# M1 Trace-to-Skill gate: SKILL_DISTILLING may only close after an approved
# SkillCandidate exists, or the lead explicitly confirms there is nothing to
# distill (reason marker NO_DISTILL_CONFIRMED; see native_mcp.py).
SKILL_DISTILL_CLOSE_PRECONDITION: Tuple[str, str] = ("SKILL_DISTILLING", "CLOSED")

# Failure-signature circuit breaker: when FAIL VerificationReports carrying the
# same failure_signature reach the threshold, re-entering a verification state
# is denied — the task must escalate to NEEDS_HUMAN instead of retrying the
# same loop. The count is per task and cannot be evaded by rewriting task ids.
FAILURE_SIGNATURE_BREAKER_THRESHOLD: int = 3
BREAKER_GUARDED_TARGETS: Tuple[str, ...] = ("VERIFYING", "READONLY_VERIFYING")

# Who may write side-effect ledger entries (query-ledger-before-execute).
SIDE_EFFECT_WRITERS: Tuple[str, ...] = ("codeops-executor", "codeops-lead")
SIDE_EFFECT_STATUSES: Tuple[str, ...] = ("INTENT", "EXECUTED", "FAILED", "ROLLED_BACK")

# Short duty text per state, surfaced by state_describe so that a Worker
# (or a fresh recovery session) can read its workstation contract directly
# instead of inferring it from the full chain history.
STATE_DUTY: Dict[str, str] = {
    "RECEIVED": "任务已登记，intake 做多源聚合去重并产出 IssueCluster",
    "FUSED": "聚合完成，triage 做风险定级并判定只读/修复分支",
    "TRIAGED": "定级完成，env-bootstrap 做环境快照（只采集不修改）",
    "BOOTSTRAPPED": "环境就绪，repo-analyst 做只读根因定位，假设须锚定代码位置",
    "LOCATED": "根因已封板：修复路径进 PLANNED，只读路径进 READONLY_VERIFYING",
    "PLANNED": "plan 产出 ChangePlan 并发起人工审批",
    "AWAITING_APPROVAL": "人工审批闸口：审批通过后 executor 才能写入 PatchBundle 并推进",
    "PATCHED": "补丁已落，verifier 进入独立验证",
    "VERIFYING": "verifier 独立工作区重跑测试取证；PASS 进 RELEASE_READY，FAIL 附 failure_signature 转 NEEDS_HUMAN",
    "RELEASE_READY": "验证通过确认，postmortem 复盘归档",
    "POSTMORTEM": "复盘完成，轨迹蒸馏产出 SkillCandidate 或确认无蒸馏价值",
    "SKILL_DISTILLING": "蒸馏门禁：须存在 approved SkillCandidate 或 NO_DISTILL_CONFIRMED 才能关单",
    "READONLY_VERIFYING": "verifier 独立验证根因假设，禁止引用他人结论",
    "READONLY_VERIFIED": "只读验证通过，lead 做证据封板",
    "EVIDENCE_PACKED": "证据包校验通过，lead 关单",
    "NEEDS_HUMAN": "人工裁决：可退回 TRIAGED/LOCATED/PLANNED/READONLY_VERIFYING 或关单",
    "RECOVERING": "崩溃恢复：由 lead 发起，回到断点状态续跑，版本号不变",
    "RETRYABLE_FAILURE": "环节级可重试失败，修复条件后回到原环节",
    "BLOCKED_BY_POLICY": "审批拒绝或越权，人工裁决或关单",
    "CLOSED": "终态",
}

# All state names known to the state machine (used by validators).
ALL_STATES: Set[str] = set(TRANSITIONS)
READONLY_BRANCH_STATES: List[str] = ["READONLY_VERIFYING", "READONLY_VERIFIED", "EVIDENCE_PACKED"]
