"""Transactional state and approval MCP service for native AgentTeams runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .state_machine_def import (
    ACTOR_TARGETS,
    ARTIFACT_ALLOWED_STATES,
    ARTIFACT_PRODUCERS,
    ARTIFACT_REQUIRED_FIELDS,
    BREAKER_GUARDED_TARGETS,
    EVIDENCE_PACKED_PRECONDITION,
    FAILURE_SIGNATURE_BREAKER_THRESHOLD,
    SIDE_EFFECT_STATUSES,
    SIDE_EFFECT_WRITERS,
    SKILL_DISTILL_CLOSE_PRECONDITION,
    STATE_DUTY,
    TRANSITIONS,
    TRANSITION_REQUIRED_ARTIFACTS,
    TRANSITION_REQUIRED_VERDICT,
)


class AuthorityError(RuntimeError):
    code = "AUTHORITY_ERROR"


class ConflictError(AuthorityError):
    code = "CONFLICT"


class AuthorizationError(AuthorityError):
    code = "UNAUTHORIZED"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


class SQLiteStateAuthority:
    """Single-writer state authority with transactional compare-and-swap."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    input_payload TEXT NOT NULL,
                    state TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_digest TEXT NOT NULL,
                    requested_state TEXT NOT NULL,
                    requested_state_version INTEGER NOT NULL,
                    expected_state TEXT NOT NULL,
                    expected_decision_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reviewer_identity TEXT,
                    decision_evidence TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    producer TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS side_effects (
                    effect_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, idempotency_key)
                );
                """
            )
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _task(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "trace_id": row["trace_id"],
            "domain": row["domain"],
            "input_payload": json.loads(row["input_payload"]),
            "state": row["state"],
            "state_version": row["state_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _event(self, conn: sqlite3.Connection, task: sqlite3.Row, event_type: str, actor: str, payload: Dict[str, Any], state_version: Optional[int] = None) -> str:
        item_id = new_id("evt")
        conn.execute(
            "INSERT INTO events(event_id, task_id, trace_id, event_type, actor, state_version, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, task["task_id"], task["trace_id"], event_type, actor, task["state_version"] if state_version is None else state_version, canonical_json(payload), utc_now()),
        )
        return item_id

    def create_task(self, task_id: str, domain: str, input_payload: Dict[str, Any], trace_id: Optional[str] = None) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if existing:
                if existing["domain"] == domain and existing["input_payload"] == canonical_json(input_payload):
                    result = self._task(existing)
                    result["created"] = False
                    return result
                raise ConflictError("TASK_ID_REUSE_WITH_DIFFERENT_INPUT")
            timestamp = utc_now()
            task_trace = trace_id or new_id("trace")
            conn.execute(
                "INSERT INTO tasks(task_id, trace_id, domain, input_payload, state, state_version, created_at, updated_at) VALUES (?, ?, ?, ?, 'RECEIVED', 0, ?, ?)",
                (task_id, task_trace, domain, canonical_json(input_payload), timestamp, timestamp),
            )
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            self._event(conn, row, "TASK_CREATED", "codeops-lead", {"domain": domain, "input_digest": digest(input_payload)})
            result = self._task(row)
            result["created"] = True
            return result

    def get_task(self, task_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise AuthorityError("TASK_NOT_FOUND")
        return self._task(row)

    def state_describe(self, task_id: str, actor: str) -> Dict[str, Any]:
        """Agent workstation contract derived from state_machine_def: what inputs
        exist, what this actor may produce here, which transitions it owns and
        under what exit criteria, and where failures go. Read-only."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                raise AuthorityError("TASK_NOT_FOUND")
            task = self._task(row)
            state = task["state"]
            artifacts = [
                {
                    "artifact_id": item["artifact_id"],
                    "artifact_type": item["artifact_type"],
                    "producer": item["producer"],
                    "state_version": item["state_version"],
                    "content_digest": item["content_digest"],
                }
                for item in conn.execute(
                    "SELECT artifact_id, artifact_type, producer, state_version, content_digest FROM artifacts WHERE task_id = ? ORDER BY created_at",
                    (task_id,),
                ).fetchall()
            ]
            reports = conn.execute(
                "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = 'VerificationReport'",
                (task_id,),
            ).fetchall()
        owned_targets = ACTOR_TARGETS.get(actor, set())
        legal_targets = TRANSITIONS.get(state, set())
        allowed = sorted(legal_targets & owned_targets)
        blocked = sorted(legal_targets - owned_targets)
        expected_outputs = sorted(
            artifact_type
            for artifact_type, producer in ARTIFACT_PRODUCERS.items()
            if producer == actor and state in ARTIFACT_ALLOWED_STATES.get(artifact_type, set())
        )
        exit_criteria = []
        for target in allowed:
            required = TRANSITION_REQUIRED_ARTIFACTS.get((state, target))
            if required:
                artifact_type, current_version_only = required
                criterion = "requires %s" % artifact_type
                verdict = TRANSITION_REQUIRED_VERDICT.get((state, target))
                if verdict:
                    criterion += " with verdict=%s" % verdict
                if current_version_only:
                    criterion += " (written at current version)"
                exit_criteria.append({"target": target, "requires": criterion})
            if (state, target) == EVIDENCE_PACKED_PRECONDITION:
                exit_criteria.append({"target": target, "requires": "evidence_pack validation passes inside the authority"})
            if (state, target) == SKILL_DISTILL_CLOSE_PRECONDITION:
                exit_criteria.append({"target": target, "requires": "approved SkillCandidate exists, or reason contains NO_DISTILL_CONFIRMED"})
            if state == "AWAITING_APPROVAL" and target == "PATCHED":
                exit_criteria.append({"target": target, "requires": "APPROVED approval bound to a PatchBundle at current version"})
            if target in BREAKER_GUARDED_TARGETS:
                exit_criteria.append({"target": target, "requires": "no failure_signature tripped the %dx breaker" % FAILURE_SIGNATURE_BREAKER_THRESHOLD})
        fail_counts: Dict[str, int] = {}
        for item in reports:
            payload = json.loads(item["payload"])
            if payload.get("verdict") != "FAIL":
                continue
            signature = str(payload.get("failure_signature") or "").strip()
            if signature:
                fail_counts[signature] = fail_counts.get(signature, 0) + 1
        tripped = sorted(s for s, c in fail_counts.items() if c >= FAILURE_SIGNATURE_BREAKER_THRESHOLD)
        return {
            "task_id": task_id,
            "trace_id": task["trace_id"],
            "state": state,
            "state_version": task["state_version"],
            "you_are": actor,
            "duty": STATE_DUTY.get(state, ""),
            "available_inputs": artifacts,
            "expected_outputs": expected_outputs,
            "allowed_transitions": allowed,
            "blocked_transitions": blocked,
            "exit_criteria": exit_criteria,
            "failure_signature_counts": fail_counts,
            "breaker_tripped": tripped,
            "on_failure": "如实报告失败并附 failure_signature；同一签名失败达 %d 次后协议拒绝再进验证态，必须升级 NEEDS_HUMAN" % FAILURE_SIGNATURE_BREAKER_THRESHOLD,
        }

    def record_side_effect_intent(self, task_id: str, kind: str, idempotency_key: str, intent: Dict[str, Any], actor: str) -> Dict[str, Any]:
        """Query-ledger-before-execute: record (or replay) the intent of an
        external side effect. Idempotent per (task_id, idempotency_key)."""
        if actor not in SIDE_EFFECT_WRITERS:
            raise AuthorizationError("ACTOR_CANNOT_WRITE_SIDE_EFFECT_LEDGER actor=%s" % actor)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not task:
                raise AuthorityError("TASK_NOT_FOUND")
            existing = conn.execute(
                "SELECT * FROM side_effects WHERE task_id = ? AND idempotency_key = ?",
                (task_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["kind"] != kind or existing["intent"] != canonical_json(intent):
                    raise ConflictError("SIDE_EFFECT_IDEMPOTENCY_KEY_REUSE_WITH_DIFFERENT_INTENT")
                result = self._side_effect(existing)
                result["created"] = False
                return result
            timestamp = utc_now()
            effect_id = new_id("fx")
            conn.execute(
                "INSERT INTO side_effects(effect_id, task_id, trace_id, kind, idempotency_key, intent, status, result, actor, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'INTENT', NULL, ?, ?, ?)",
                (effect_id, task_id, task["trace_id"], kind, idempotency_key, canonical_json(intent), actor, timestamp, timestamp),
            )
            self._event(conn, task, "SIDE_EFFECT_INTENT", actor, {"effect_id": effect_id, "kind": kind, "idempotency_key": idempotency_key, "intent_digest": digest(intent)})
            result = self._side_effect(conn.execute("SELECT * FROM side_effects WHERE effect_id = ?", (effect_id,)).fetchone())
            result["created"] = True
            return result

    def record_side_effect_result(self, effect_id: str, status: str, result_payload: Dict[str, Any], actor: str) -> Dict[str, Any]:
        if actor not in SIDE_EFFECT_WRITERS:
            raise AuthorizationError("ACTOR_CANNOT_WRITE_SIDE_EFFECT_LEDGER actor=%s" % actor)
        if status not in SIDE_EFFECT_STATUSES or status == "INTENT":
            raise AuthorityError("INVALID_SIDE_EFFECT_STATUS %s" % status)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM side_effects WHERE effect_id = ?", (effect_id,)).fetchone()
            if not row:
                raise AuthorityError("SIDE_EFFECT_NOT_FOUND")
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            conn.execute(
                "UPDATE side_effects SET status = ?, result = ?, updated_at = ? WHERE effect_id = ?",
                (status, canonical_json(result_payload), utc_now(), effect_id),
            )
            self._event(conn, task, "SIDE_EFFECT_RESULT", actor, {"effect_id": effect_id, "status": status, "result_digest": digest(result_payload)})
            return self._side_effect(conn.execute("SELECT * FROM side_effects WHERE effect_id = ?", (effect_id,)).fetchone())

    def list_side_effects(self, task_id: str) -> Dict[str, Any]:
        """Recovery re-read: the ledger is consulted before re-executing any
        external effect so a recovered run never repeats a completed one."""
        with self._connect() as conn:
            task = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not task:
                raise AuthorityError("TASK_NOT_FOUND")
            rows = conn.execute(
                "SELECT * FROM side_effects WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return {"task_id": task_id, "side_effects": [self._side_effect(row) for row in rows]}

    @staticmethod
    def _side_effect(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "effect_id": row["effect_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "idempotency_key": row["idempotency_key"],
            "intent": json.loads(row["intent"]),
            "status": row["status"],
            "result": json.loads(row["result"]) if row["result"] else None,
            "actor": row["actor"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def transition(self, task_id: str, target: str, actor: str, reason: str, expected_state_version: int) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                raise AuthorityError("TASK_NOT_FOUND")
            if row["state_version"] != expected_state_version:
                raise ConflictError("STALE_STATE expected=%d found=%d" % (expected_state_version, row["state_version"]))
            if target not in TRANSITIONS.get(row["state"], set()):
                raise AuthorityError("INVALID_TRANSITION %s -> %s" % (row["state"], target))
            if target not in ACTOR_TARGETS.get(actor, set()):
                raise AuthorizationError("ACTOR_CANNOT_OWN_TARGET actor=%s target=%s" % (actor, target))
            self._enforce_transition_preconditions(conn, task_id, row["state"], target, expected_state_version, reason)
            if row["state"] == "AWAITING_APPROVAL" and target == "PATCHED":
                approval = conn.execute(
                    "SELECT * FROM approvals WHERE task_id = ? AND status = 'APPROVED' AND expected_state = ? AND expected_decision_version = ? ORDER BY decided_at DESC LIMIT 1",
                    (task_id, row["state"], expected_state_version),
                ).fetchone()
                if not approval:
                    raise AuthorizationError("APPROVED_SCOPE_REQUIRED")
                patch_bundles = conn.execute(
                    "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = 'PatchBundle' AND producer = 'codeops-executor' AND state_version = ?",
                    (task_id, expected_state_version),
                ).fetchall()
                if not any(json.loads(item["payload"]).get("approval_id") == approval["approval_id"] for item in patch_bundles):
                    raise AuthorizationError("APPROVAL_BOUND_PATCH_BUNDLE_REQUIRED")
            next_version = expected_state_version + 1
            updated = conn.execute(
                "UPDATE tasks SET state = ?, state_version = ?, updated_at = ? WHERE task_id = ? AND state_version = ?",
                (target, next_version, utc_now(), task_id, expected_state_version),
            )
            if updated.rowcount != 1:
                raise ConflictError("CAS_UPDATE_FAILED")
            self._event(conn, row, "STATE_TRANSITION", actor, {"from": row["state"], "to": target, "reason": reason}, next_version)
            return self._task(conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone())

    def _enforce_transition_preconditions(self, conn: sqlite3.Connection, task_id: str, source: str, target: str, expected_state_version: int, reason: str = "") -> None:
        required = TRANSITION_REQUIRED_ARTIFACTS.get((source, target))
        if required:
            artifact_type, current_version_only = required
            if current_version_only:
                rows = conn.execute(
                    "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = ? AND state_version = ?",
                    (task_id, artifact_type, expected_state_version),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = ?",
                    (task_id, artifact_type),
                ).fetchall()
            if not rows:
                raise AuthorizationError(
                    "TRANSITION_REQUIRES_%s %s -> %s" % (artifact_type.upper(), source, target)
                )
            verdict_required = TRANSITION_REQUIRED_VERDICT.get((source, target))
            if verdict_required and not any(
                json.loads(item["payload"]).get("verdict") == verdict_required for item in rows
            ):
                raise AuthorizationError(
                    "TRANSITION_REQUIRES_%s_VERDICT_%s %s -> %s" % (artifact_type.upper(), verdict_required, source, target)
                )
        if (source, target) == EVIDENCE_PACKED_PRECONDITION:
            validation = self.validate_evidence_pack(task_id)
            if not validation["valid"]:
                raise AuthorityError(
                    "EVIDENCE_PACK_INVALID: %s" % "; ".join(validation["errors"])
                )
        if (source, target) == SKILL_DISTILL_CLOSE_PRECONDITION:
            rows = conn.execute(
                "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = 'SkillCandidate'",
                (task_id,),
            ).fetchall()
            approved = any(
                json.loads(item["payload"]).get("review_status") == "approved" for item in rows
            )
            if not approved and "NO_DISTILL_CONFIRMED" not in reason:
                raise AuthorizationError(
                    "SKILL_DISTILL_CLOSE_REQUIRES_APPROVED_CANDIDATE_OR_NO_DISTILL_CONFIRMED"
                )
        if target in BREAKER_GUARDED_TARGETS:
            rows = conn.execute(
                "SELECT payload FROM artifacts WHERE task_id = ? AND artifact_type = 'VerificationReport'",
                (task_id,),
            ).fetchall()
            fail_counts: Dict[str, int] = {}
            for item in rows:
                payload = json.loads(item["payload"])
                if payload.get("verdict") != "FAIL":
                    continue
                signature = str(payload.get("failure_signature") or "").strip()
                if not signature:
                    continue
                fail_counts[signature] = fail_counts.get(signature, 0) + 1
            tripped = [(s, c) for s, c in fail_counts.items() if c >= FAILURE_SIGNATURE_BREAKER_THRESHOLD]
            if tripped:
                signature, count = sorted(tripped, key=lambda pair: -pair[1])[0]
                raise AuthorizationError(
                    "FAILURE_SIGNATURE_BREAKER_TRIPPED signature=%s count=%d threshold=%d -> escalate NEEDS_HUMAN"
                    % (signature, count, FAILURE_SIGNATURE_BREAKER_THRESHOLD)
                )

    def request_approval(self, task_id: str, actor: str, scope: Dict[str, Any], expected_state: str, expected_state_version: int) -> Dict[str, Any]:
        if actor != "codeops-plan":
            raise AuthorizationError("ONLY_PLANNER_REQUESTS_CHANGE_APPROVAL")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not task:
                raise AuthorityError("TASK_NOT_FOUND")
            if task["state_version"] != expected_state_version:
                raise ConflictError("STALE_APPROVAL_REQUEST")
            approval_id = new_id("approval")
            scope_hash = digest(scope)
            decision_version = expected_state_version + (0 if task["state"] == expected_state else 1)
            created_at = utc_now()
            conn.execute(
                "INSERT INTO approvals(approval_id, task_id, trace_id, requested_by, scope, scope_digest, requested_state, requested_state_version, expected_state, expected_decision_version, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
                (approval_id, task_id, task["trace_id"], actor, canonical_json(scope), scope_hash, task["state"], expected_state_version, expected_state, decision_version, created_at),
            )
            self._event(conn, task, "APPROVAL_REQUESTED", actor, {"approval_id": approval_id, "scope_digest": scope_hash, "expected_state": expected_state})
            return {
                "approval_id": approval_id,
                "task_id": task_id,
                "trace_id": task["trace_id"],
                "scope_digest": scope_hash,
                "requested_state": task["state"],
                "requested_state_version": expected_state_version,
                "expected_state": expected_state,
                "expected_decision_version": decision_version,
                "status": "PENDING",
                "created_at": created_at,
            }

    def decide_approval(self, approval_id: str, reviewer_identity: str, decision: str, scope_digest: str, room_id: str, event_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            approval = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
            if not approval:
                raise AuthorityError("APPROVAL_NOT_FOUND")
            if approval["status"] != "PENDING":
                raise ConflictError("APPROVAL_NOT_PENDING")
            if decision not in {"APPROVED", "REJECTED"}:
                raise AuthorityError("INVALID_APPROVAL_DECISION")
            if scope_digest != approval["scope_digest"]:
                raise ConflictError("APPROVAL_SCOPE_MISMATCH")
            if not room_id or not event_id or not reviewer_identity:
                raise AuthorityError("MATRIX_EVIDENCE_REQUIRED")
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (approval["task_id"],)).fetchone()
            if task["state"] != approval["expected_state"] or task["state_version"] != approval["expected_decision_version"]:
                raise ConflictError("APPROVAL_STALE")
            evidence = {
                "provider": "matrix",
                "reviewer_identity": reviewer_identity,
                "scope_digest": scope_digest,
                "room_id": room_id,
                "event_id": event_id,
            }
            decided_at = utc_now()
            conn.execute(
                "UPDATE approvals SET status = ?, reviewer_identity = ?, decision_evidence = ?, decided_at = ? WHERE approval_id = ? AND status = 'PENDING'",
                (decision, reviewer_identity, canonical_json(evidence), decided_at, approval_id),
            )
            self._event(conn, task, "APPROVAL_DECIDED", reviewer_identity, {"approval_id": approval_id, "decision": decision, "decision_evidence": evidence})
            return {"approval_id": approval_id, "status": decision, "decision_evidence": evidence, "decided_at": decided_at}

    def get_approval(self, approval_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            approval = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if not approval:
            raise AuthorityError("APPROVAL_NOT_FOUND")
        return {
            "approval_id": approval["approval_id"],
            "task_id": approval["task_id"],
            "trace_id": approval["trace_id"],
            "requested_by": approval["requested_by"],
            "scope": json.loads(approval["scope"]),
            "scope_digest": approval["scope_digest"],
            "expected_state": approval["expected_state"],
            "expected_decision_version": approval["expected_decision_version"],
            "status": approval["status"],
            "reviewer_identity": approval["reviewer_identity"],
            "decision_evidence": json.loads(approval["decision_evidence"]) if approval["decision_evidence"] else None,
            "created_at": approval["created_at"],
            "decided_at": approval["decided_at"],
        }

    def put_artifact(self, task_id: str, artifact_type: str, producer: str, payload: Dict[str, Any], evidence_refs: Sequence[str], expected_state_version: int) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not task:
                raise AuthorityError("TASK_NOT_FOUND")
            if task["state_version"] != expected_state_version:
                raise ConflictError("STALE_ARTIFACT_WRITE")
            expected_producer = ARTIFACT_PRODUCERS.get(artifact_type)
            if not expected_producer:
                raise AuthorityError("UNKNOWN_ARTIFACT_TYPE %s" % artifact_type)
            if producer != expected_producer:
                raise AuthorizationError("ARTIFACT_PRODUCER_MISMATCH type=%s producer=%s" % (artifact_type, producer))
            allowed_states = ARTIFACT_ALLOWED_STATES.get(artifact_type, set())
            if task["state"] not in allowed_states:
                raise AuthorityError(
                    "ARTIFACT_STATE_MISMATCH type=%s state=%s allowed=%s"
                    % (artifact_type, task["state"], ",".join(sorted(allowed_states)))
                )
            if artifact_type != "PatchBundle":
                missing = [field for field in ARTIFACT_REQUIRED_FIELDS.get(artifact_type, ()) if field not in payload]
                if missing:
                    raise AuthorityError(
                        "ARTIFACT_PAYLOAD_FIELDS_MISSING type=%s missing=%s" % (artifact_type, ",".join(missing))
                    )
            if artifact_type == "PatchBundle":
                approval_id = payload.get("approval_id")
                changed_files = payload.get("changed_files")
                if not isinstance(approval_id, str) or not approval_id or not isinstance(changed_files, list) or not changed_files:
                    raise AuthorityError("PATCH_BUNDLE_APPROVAL_AND_CHANGED_FILES_REQUIRED")
                approval = conn.execute(
                    "SELECT * FROM approvals WHERE approval_id = ? AND task_id = ? AND status = 'APPROVED'",
                    (approval_id, task_id),
                ).fetchone()
                if not approval:
                    raise AuthorizationError("PATCH_BUNDLE_APPROVAL_INVALID")
                if task["state"] == "AWAITING_APPROVAL" and (
                    approval["expected_state"] != task["state"]
                    or approval["expected_decision_version"] != expected_state_version
                ):
                    raise ConflictError("PATCH_BUNDLE_APPROVAL_STALE")
                approved_files = json.loads(approval["scope"]).get("files", [])
                if not all(isinstance(path, str) and path in approved_files for path in changed_files):
                    raise AuthorizationError("PATCH_BUNDLE_OUTSIDE_APPROVED_SCOPE")
            artifact_id = new_id("art")
            content_hash = digest(payload)
            created_at = utc_now()
            conn.execute(
                "INSERT INTO artifacts(artifact_id, task_id, trace_id, artifact_type, producer, state_version, payload, evidence_refs, content_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, task_id, task["trace_id"], artifact_type, producer, expected_state_version, canonical_json(payload), canonical_json(list(evidence_refs)), content_hash, created_at),
            )
            self._event(conn, task, "ARTIFACT_PUBLISHED", producer, {"artifact_id": artifact_id, "artifact_type": artifact_type, "content_digest": content_hash})
            return {"artifact_id": artifact_id, "task_id": task_id, "trace_id": task["trace_id"], "artifact_type": artifact_type, "producer": producer, "state_version": expected_state_version, "content_digest": content_hash, "created_at": created_at}

    def evidence_pack(self, task_id: str, validate: bool = False) -> Dict[str, Any]:
        with self._connect() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not task:
                raise AuthorityError("TASK_NOT_FOUND")
            events = [dict(row) for row in conn.execute("SELECT * FROM events WHERE task_id = ? ORDER BY sequence", (task_id,))]
            approvals = [dict(row) for row in conn.execute("SELECT * FROM approvals WHERE task_id = ? ORDER BY created_at", (task_id,))]
            artifacts = [dict(row) for row in conn.execute("SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at", (task_id,))]
        for event in events:
            event["payload"] = json.loads(event["payload"])
            event.pop("sequence", None)
        for approval in approvals:
            approval["scope"] = json.loads(approval["scope"])
            approval["decision_evidence"] = json.loads(approval["decision_evidence"]) if approval["decision_evidence"] else None
        for artifact in artifacts:
            artifact["payload"] = json.loads(artifact["payload"])
            artifact["evidence_refs"] = json.loads(artifact["evidence_refs"])
        pack = {"schema_version": "1.0", "task": self._task(task), "events": events, "approvals": approvals, "artifacts": artifacts}
        if validate:
            pack["validation"] = self.validate_evidence_pack(task_id)
        return pack

    def validate_evidence_pack(self, task_id: str) -> Dict[str, Any]:
        """Independently re-check an exported pack against the authority rules.

        This replays the state chain and re-derives every digest; it does not
        trust any field in the pack itself. Used both by the export tool
        (validate=true) and as the entry gate for EVIDENCE_PACKED.
        """
        pack = self.evidence_pack(task_id)
        errors: list[str] = []
        task = pack["task"]
        events = pack["events"]
        approvals = pack["approvals"]
        artifacts = pack["artifacts"]

        if not events or events[0]["event_type"] != "TASK_CREATED":
            errors.append("GENESIS_EVENT_MISSING")

        transitions = [event for event in events if event["event_type"] == "STATE_TRANSITION"]
        expected_version = 0
        visited_states: list[str] = ["RECEIVED"]
        for item in transitions:
            expected_version += 1
            payload = item["payload"]
            source, target = payload.get("from"), payload.get("to")
            if item["state_version"] != expected_version:
                errors.append("VERSION_CHAIN_BROKEN at event %s" % item["event_id"])
            if source != visited_states[-1]:
                errors.append("STATE_CHAIN_BROKEN at event %s" % item["event_id"])
            if target not in TRANSITIONS.get(source, set()):
                errors.append("INVALID_TRANSITION_RECORDED %s -> %s" % (source, target))
            if target not in ACTOR_TARGETS.get(item["actor"], set()):
                errors.append("UNAUTHORIZED_ACTOR_RECORDED actor=%s target=%s" % (item["actor"], target))
            visited_states.append(target)
        if task["state_version"] != expected_version:
            errors.append("TASK_VERSION_MISMATCH expected=%d found=%d" % (expected_version, task["state_version"]))
        if task["state"] != visited_states[-1]:
            errors.append("TASK_STATE_MISMATCH expected=%s found=%s" % (visited_states[-1], task["state"]))

        for artifact in artifacts:
            if ARTIFACT_PRODUCERS.get(artifact["artifact_type"]) != artifact["producer"]:
                errors.append("ARTIFACT_PRODUCER_MISMATCH id=%s" % artifact["artifact_id"])
            if digest(artifact["payload"]) != artifact["content_digest"]:
                errors.append("ARTIFACT_DIGEST_MISMATCH id=%s" % artifact["artifact_id"])
            missing = [field for field in ARTIFACT_REQUIRED_FIELDS.get(artifact["artifact_type"], ()) if field not in artifact["payload"]]
            if missing:
                errors.append("ARTIFACT_FIELDS_MISSING id=%s missing=%s" % (artifact["artifact_id"], ",".join(missing)))

        for approval in approvals:
            if digest(approval["scope"]) != approval["scope_digest"]:
                errors.append("APPROVAL_SCOPE_DIGEST_MISMATCH id=%s" % approval["approval_id"])
            if approval["status"] == "APPROVED":
                evidence = approval.get("decision_evidence") or {}
                if not (evidence.get("room_id") and evidence.get("event_id") and evidence.get("reviewer_identity")):
                    errors.append("APPROVAL_MATRIX_EVIDENCE_MISSING id=%s" % approval["approval_id"])

        verified = any(state in {"VERIFYING", "READONLY_VERIFYING"} for state in visited_states)
        terminal = task["state"] in {"RELEASE_READY", "EVIDENCE_PACKED", "CLOSED"}
        if (verified or terminal) and not any(a["artifact_type"] == "VerificationReport" for a in artifacts):
            errors.append("VERIFICATION_REPORT_MISSING")
        if task["state"] in {"RELEASE_READY", "READONLY_VERIFIED", "EVIDENCE_PACKED"} or (
            task["state"] == "CLOSED" and verified
        ):
            passing = [a for a in artifacts if a["artifact_type"] == "VerificationReport" and a["payload"].get("verdict") == "PASS"]
            if not passing:
                errors.append("PASSING_VERIFICATION_REPORT_MISSING")
        if task["state"] == "EVIDENCE_PACKED" and "READONLY_VERIFIED" not in visited_states:
            errors.append("READONLY_VERIFIED_NOT_IN_CHAIN")

        return {"valid": not errors, "errors": errors}


TOOLS = [
    {"name": "task_create", "description": "Idempotently create a task.", "inputSchema": {"type": "object", "required": ["task_id", "domain", "input_payload"], "properties": {"task_id": {"type": "string"}, "domain": {"type": "string"}, "input_payload": {"type": "object"}, "trace_id": {"type": "string"}}}},
    {"name": "task_get", "description": "Read authoritative task state.", "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
    {"name": "state_transition", "description": "CAS transition a task using the authenticated Worker identity.", "inputSchema": {"type": "object", "required": ["task_id", "target", "reason", "expected_state_version"], "properties": {"task_id": {"type": "string"}, "target": {"type": "string"}, "reason": {"type": "string"}, "expected_state_version": {"type": "integer"}}}},
    {"name": "approval_request", "description": "Create a scope-bound Human approval request.", "inputSchema": {"type": "object", "required": ["task_id", "scope", "expected_state", "expected_state_version"], "properties": {"task_id": {"type": "string"}, "scope": {"type": "object"}, "expected_state": {"type": "string"}, "expected_state_version": {"type": "integer"}}}},
    {"name": "approval_decide", "description": "Record a Matrix-backed approval decision.", "inputSchema": {"type": "object", "required": ["approval_id", "reviewer_identity", "decision", "scope_digest", "room_id", "event_id"], "properties": {"approval_id": {"type": "string"}, "reviewer_identity": {"type": "string"}, "decision": {"enum": ["APPROVED", "REJECTED"]}, "scope_digest": {"type": "string"}, "room_id": {"type": "string"}, "event_id": {"type": "string"}}}},
    {"name": "approval_status", "description": "Read one scope- and Matrix-bound approval decision.", "inputSchema": {"type": "object", "required": ["approval_id"], "properties": {"approval_id": {"type": "string"}}}},
    {"name": "artifact_put", "description": "Publish a typed artifact at an exact task version.", "inputSchema": {"type": "object", "required": ["task_id", "artifact_type", "payload", "expected_state_version"], "properties": {"task_id": {"type": "string"}, "artifact_type": {"type": "string"}, "payload": {"type": "object"}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "expected_state_version": {"type": "integer"}}}},
    {"name": "evidence_pack", "description": "Export authoritative task events, approvals and artifacts; validate=true additionally replays and checks the full chain.", "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}, "validate": {"type": "boolean"}}}},
    {"name": "state_describe", "description": "Agent workstation contract for the caller: available inputs, expected outputs, owned transitions with exit criteria, breaker status, failure policy. Derived from the state machine definition; read-only.", "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
    {"name": "side_effect_intent", "description": "Query-ledger-before-execute: idempotently record the intent of an external side effect before performing it.", "inputSchema": {"type": "object", "required": ["task_id", "kind", "idempotency_key", "intent"], "properties": {"task_id": {"type": "string"}, "kind": {"type": "string"}, "idempotency_key": {"type": "string"}, "intent": {"type": "object"}}}},
    {"name": "side_effect_result", "description": "Record the outcome (EXECUTED/FAILED/ROLLED_BACK) of a previously registered side effect intent.", "inputSchema": {"type": "object", "required": ["effect_id", "status", "result"], "properties": {"effect_id": {"type": "string"}, "status": {"enum": ["EXECUTED", "FAILED", "ROLLED_BACK"]}, "result": {"type": "object"}}}},
    {"name": "side_effect_list", "description": "Recovery re-read: list the side-effect ledger of a task so a recovered run never repeats a completed effect.", "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
]


def handle_mcp_jsonrpc(
    authority: SQLiteStateAuthority,
    identity_tokens: Dict[str, str],
    path: str,
    headers: Dict[str, str],
    request: Dict[str, Any],
) -> tuple[int, Optional[Dict[str, Any]]]:
    if path != "/mcp":
        return 404, {"error": "not found"}
    token = headers.get("Authorization", "").removeprefix("Bearer ").strip()
    actor = identity_tokens.get(token)
    if not actor:
        return 401, {"error": "invalid worker identity token"}
    try:
        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized":
            return 202, None
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "codeops-state-mcp", "version": "0.1.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = request.get("params", {})
            value = dispatch_tool(authority, params.get("name", ""), params.get("arguments", {}), actor)
            result = {"content": [{"type": "text", "text": canonical_json(value)}], "structuredContent": value, "isError": False}
        else:
            raise AuthorityError("METHOD_NOT_FOUND")
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (AuthorityError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        code = getattr(exc, "code", "INVALID_ARGUMENT")
        return 200, {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32000, "message": str(exc), "data": {"authority_code": code}}}


def dispatch_tool(authority: SQLiteStateAuthority, tool: str, arguments: Dict[str, Any], actor: str) -> Dict[str, Any]:
    if tool == "task_create":
        if actor != "codeops-lead":
            raise AuthorizationError("ONLY_LEADER_CREATES_TASKS")
        return authority.create_task(arguments["task_id"], arguments["domain"], arguments["input_payload"], arguments.get("trace_id"))
    if tool == "task_get":
        return authority.get_task(arguments["task_id"])
    if tool == "state_transition":
        return authority.transition(arguments["task_id"], arguments["target"], actor, arguments["reason"], int(arguments["expected_state_version"]))
    if tool == "approval_request":
        return authority.request_approval(arguments["task_id"], actor, arguments["scope"], arguments["expected_state"], int(arguments["expected_state_version"]))
    if tool == "approval_decide":
        if actor != "codeops-lead":
            raise AuthorizationError("ONLY_LEADER_RECORDS_MATRIX_DECISIONS")
        return authority.decide_approval(arguments["approval_id"], arguments["reviewer_identity"], arguments["decision"], arguments["scope_digest"], arguments["room_id"], arguments["event_id"])
    if tool == "approval_status":
        return authority.get_approval(arguments["approval_id"])
    if tool == "artifact_put":
        return authority.put_artifact(arguments["task_id"], arguments["artifact_type"], actor, arguments["payload"], arguments.get("evidence_refs", []), int(arguments["expected_state_version"]))
    if tool == "evidence_pack":
        return authority.evidence_pack(arguments["task_id"], validate=bool(arguments.get("validate", False)))
    if tool == "state_describe":
        return authority.state_describe(arguments["task_id"], actor)
    if tool == "side_effect_intent":
        return authority.record_side_effect_intent(arguments["task_id"], arguments["kind"], arguments["idempotency_key"], arguments["intent"], actor)
    if tool == "side_effect_result":
        return authority.record_side_effect_result(arguments["effect_id"], arguments["status"], arguments["result"], actor)
    if tool == "side_effect_list":
        return authority.list_side_effects(arguments["task_id"])
    raise AuthorityError("UNKNOWN_TOOL %s" % tool)


class MCPHandler(BaseHTTPRequestHandler):
    server_version = "ExoFlowStateMCP/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: Optional[Dict[str, Any]]) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "service": "codeops-state-mcp", "transport": "streamable-http"})
            return
        self._json(405, {"error": "POST /mcp is required"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            status, payload = handle_mcp_jsonrpc(
                self.server.authority,  # type: ignore[attr-defined]
                self.server.identity_tokens,  # type: ignore[attr-defined]
                self.path,
                dict(self.headers.items()),
                request,
            )
            self._json(status, payload)
        except (AuthorityError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            code = getattr(exc, "code", "INVALID_ARGUMENT")
            self._json(200, {"jsonrpc": "2.0", "id": request.get("id") if "request" in locals() else None, "error": {"code": -32000, "message": str(exc), "data": {"authority_code": code}}})


class NativeMCPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], authority: SQLiteStateAuthority, identity_tokens: Dict[str, str]) -> None:
        super().__init__(address, MCPHandler)
        self.authority = authority
        self.identity_tokens = identity_tokens


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ExoFlow transactional MCP state authority")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--database", type=Path, default=Path("runtime_data/native/state-authority.sqlite3"))
    parser.add_argument("--identity-file", type=Path, required=True, help="JSON object mapping bearer tokens to AgentTeams Worker names")
    args = parser.parse_args(argv)
    identity_mode = stat.S_IMODE(args.identity_file.stat().st_mode)
    if identity_mode & 0o077:
        parser.error("identity file must not be accessible by group or other users")
    identities = json.loads(args.identity_file.read_text(encoding="utf-8"))
    if not identities or not all(isinstance(key, str) and isinstance(value, str) for key, value in identities.items()):
        parser.error("identity file must be a non-empty token-to-worker JSON object")
    server = NativeMCPServer((args.host, args.port), SQLiteStateAuthority(args.database), identities)
    print("ExoFlow state MCP: http://%s:%d/mcp" % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
