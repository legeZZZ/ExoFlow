#!/usr/bin/env python3
"""Dependency-free Leader state authority for the AgentTeams package.

The file is intended to be called by the Team Leader Skill against the
synced `shared/tasks/<task_id>/state.json` artifact. It is deliberately small:
MinIO/object-store synchronization remains a Provider concern, while this
module owns transition and approval invariants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


# Embedded copy of src/exoflow/state_machine_def.py.
# This file ships inside the Worker ZIP and cannot import the package, so
# tests/test_state_machine_conformance.py pins this table to the shared
# single source of truth. Any change must be made there first.
TRANSITIONS = {
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
    # Read-only analysis branch (no PatchBundle is ever produced).
    "READONLY_VERIFYING": {"READONLY_VERIFIED", "NEEDS_HUMAN", "RECOVERING"},
    "READONLY_VERIFIED": {"EVIDENCE_PACKED", "NEEDS_HUMAN", "RECOVERING"},
    "EVIDENCE_PACKED": {"CLOSED"},
    "NEEDS_HUMAN": {"TRIAGED", "LOCATED", "PLANNED", "READONLY_VERIFYING", "CLOSED", "RECOVERING"},
    "RECOVERING": {"TRIAGED", "BOOTSTRAPPED", "LOCATED", "PLANNED", "PATCHED", "VERIFYING", "READONLY_VERIFYING", "CLOSED", "NEEDS_HUMAN"},
    "RETRYABLE_FAILURE": {"BOOTSTRAPPED", "PATCHED", "NEEDS_HUMAN", "RECOVERING"},
    "BLOCKED_BY_POLICY": {"NEEDS_HUMAN", "CLOSED", "RECOVERING"},
    "CLOSED": set(),
}

ACTOR_TARGETS = {
    "codeops-intake": {"FUSED"},
    "codeops-triage": {"TRIAGED"},
    "codeops-env-bootstrap": {"BOOTSTRAPPED"},
    "codeops-repo-analyst": {"LOCATED"},
    "codeops-plan": {"PLANNED", "AWAITING_APPROVAL"},
    "codeops-executor": {"PATCHED", "RECOVERING"},
    "codeops-verifier": {"VERIFYING", "RELEASE_READY", "READONLY_VERIFYING", "READONLY_VERIFIED", "NEEDS_HUMAN"},
    "codeops-postmortem": {"POSTMORTEM", "SKILL_DISTILLING", "CLOSED"},
    # The Leader owns coordination and recovery targets only; it can never
    # move a task into a domain stage state on behalf of a Worker.
    "codeops-lead": {"RECOVERING", "NEEDS_HUMAN", "EVIDENCE_PACKED", "CLOSED"},
}


class StateMachineError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def event_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateMachineError(f"state file not found: {path}") from exc


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def append_event(state: dict, event_type: str, actor: str, payload: dict) -> None:
    state.setdefault("events", []).append({
        "event_id": event_id("evt"),
        "event_type": event_type,
        "actor": actor,
        "state_version": state["state_version"],
        "created_at": now(),
        "payload": payload,
    })


def init_state(path: Path, task_id: str, trace_id: str, domain: str) -> dict:
    if path.exists():
        raise StateMachineError(f"state already exists: {path}")
    state = {
        "schema_version": "1.0",
        "task_id": task_id,
        "trace_id": trace_id,
        "domain": domain,
        "state": "RECEIVED",
        "state_version": 0,
        "events": [],
        "approvals": [],
        "updated_at": now(),
    }
    append_event(state, "TASK_CREATED", "codeops-lead", {"domain": domain})
    save(path, state)
    return state


def transition(path: Path, target: str, actor: str, reason: str, expected_version: int) -> dict:
    state = load(path)
    if state["state_version"] != expected_version:
        raise StateMachineError(f"STALE_STATE expected={expected_version} found={state['state_version']}")
    if target not in TRANSITIONS.get(state["state"], set()):
        raise StateMachineError(f"INVALID_TRANSITION {state['state']} -> {target}")
    if target not in ACTOR_TARGETS.get(actor, set()):
        raise StateMachineError(f"UNAUTHORIZED_TARGET actor={actor} target={target}")
    previous = state["state"]
    state["state"] = target
    state["state_version"] += 1
    state["updated_at"] = now()
    append_event(state, "STATE_TRANSITION", actor, {"from": previous, "to": target, "reason": reason})
    save(path, state)
    return state


def request_approval(path: Path, actor: str, scope: dict, expected_state: str) -> dict:
    state = load(path)
    if state["state"] != expected_state:
        raise StateMachineError(f"APPROVAL_STATE_MISMATCH expected={expected_state} found={state['state']}")
    approval = {
        "approval_id": event_id("approval"),
        "task_id": state["task_id"],
        "trace_id": state["trace_id"],
        "requested_by": actor,
        "scope": scope,
        "scope_digest": digest(scope),
        "requested_state": state["state"],
        "requested_state_version": state["state_version"],
        "expected_state": expected_state,
        "status": "PENDING",
        "created_at": now(),
    }
    state.setdefault("approvals", []).append(approval)
    append_event(state, "APPROVAL_REQUESTED", actor, {"approval_id": approval["approval_id"], "scope_digest": approval["scope_digest"]})
    save(path, state)
    return approval


def approve(
    path: Path,
    approval_id: str,
    reviewer: str,
    decision: str,
    scope_digest: str,
    matrix_event_id: str,
    room_id: str,
) -> dict:
    state = load(path)
    approval = next((item for item in state.get("approvals", []) if item["approval_id"] == approval_id), None)
    if approval is None:
        raise StateMachineError(f"APPROVAL_NOT_FOUND {approval_id}")
    if approval["status"] != "PENDING":
        raise StateMachineError("APPROVAL_NOT_PENDING")
    if approval["scope_digest"] != scope_digest:
        raise StateMachineError("APPROVAL_SCOPE_MISMATCH")
    if state["state"] != approval["expected_state"] or state["state_version"] != approval["requested_state_version"]:
        raise StateMachineError("APPROVAL_STALE")
    if decision not in {"APPROVED", "REJECTED"}:
        raise StateMachineError("INVALID_DECISION")
    if not matrix_event_id or not room_id:
        raise StateMachineError("MATRIX_EVIDENCE_REQUIRED")
    evidence = {
        "provider": "matrix",
        "reviewer_identity": reviewer,
        "scope_digest": scope_digest,
        "event_id": matrix_event_id,
        "room_id": room_id,
    }
    approval.update({"status": decision, "reviewer_identity": reviewer, "decision_evidence": evidence, "decided_at": now()})
    append_event(state, "APPROVAL_DECIDED", reviewer, {"approval_id": approval_id, "decision": decision, "decision_evidence": evidence})
    save(path, state)
    return approval


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    initialize = sub.add_parser("init")
    initialize.add_argument("--state-file", type=Path, required=True)
    initialize.add_argument("--task-id", required=True)
    initialize.add_argument("--trace-id", required=True)
    initialize.add_argument("--domain", default="software-engineering")
    move = sub.add_parser("transition")
    move.add_argument("--state-file", type=Path, required=True)
    move.add_argument("--target", required=True)
    move.add_argument("--actor", required=True)
    move.add_argument("--reason", required=True)
    move.add_argument("--expected-version", type=int, required=True)
    request = sub.add_parser("request-approval")
    request.add_argument("--state-file", type=Path, required=True)
    request.add_argument("--actor", required=True)
    request.add_argument("--scope-json", required=True)
    request.add_argument("--expected-state", required=True)
    decision = sub.add_parser("approve")
    decision.add_argument("--state-file", type=Path, required=True)
    decision.add_argument("--approval-id", required=True)
    decision.add_argument("--reviewer", required=True)
    decision.add_argument("--decision", required=True)
    decision.add_argument("--scope-digest", required=True)
    decision.add_argument("--matrix-event-id", required=True)
    decision.add_argument("--room-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_state(args.state_file, args.task_id, args.trace_id, args.domain)
        elif args.command == "transition":
            result = transition(args.state_file, args.target, args.actor, args.reason, args.expected_version)
        elif args.command == "request-approval":
            result = request_approval(args.state_file, args.actor, json.loads(args.scope_json), args.expected_state)
        else:
            result = approve(
                args.state_file,
                args.approval_id,
                args.reviewer,
                args.decision,
                args.scope_digest,
                args.matrix_event_id,
                args.room_id,
            )
    except (StateMachineError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
