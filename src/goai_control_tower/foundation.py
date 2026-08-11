"""Shared AgentTeams control-plane primitives and provider contracts.

This is deliberately dependency-free. It is a local conformance runtime, not
a claim that it is the official AgentTeams service. The adapter boundary makes
the same workflows runnable against a hosted control plane later.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .state_machine_def import TRANSITIONS as _SHARED_TRANSITIONS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass
class AgentIdentity:
    agent_id: str
    role: str
    allowed_states: List[str]
    capabilities: List[str]
    can_write: List[str]
    can_call: List[str]


@dataclass
class Event:
    event_id: str
    task_id: str
    trace_id: str
    event_type: str
    actor: str
    payload: Dict[str, Any]
    state_version: int
    created_at: str = field(default_factory=utc_now)


@dataclass
class Artifact:
    artifact_id: str
    task_id: str
    trace_id: str
    artifact_type: str
    schema_version: str
    producer: str
    payload: Dict[str, Any]
    evidence_refs: List[str]
    created_at: str = field(default_factory=utc_now)


@dataclass
class Evidence:
    evidence_id: str
    task_id: str
    trace_id: str
    kind: str
    label: str
    source: str
    content: Any
    content_digest: str
    created_at: str = field(default_factory=utc_now)


@dataclass
class TaskRecord:
    task_id: str
    trace_id: str
    domain: str
    input_payload: Dict[str, Any]
    state: str
    state_version: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamTopology:
    team_id: str
    control_plane: str
    nodes: List[str]
    edges: List[Dict[str, Any]]
    execution_semantics: Dict[str, Any]


class StateTransitionError(RuntimeError):
    pass


class ConcurrentStateError(StateTransitionError):
    pass


class AuthorizationError(PermissionError):
    pass


class ApprovalError(RuntimeError):
    pass


class AgentTeamsControlPlane:
    """Authoritative task state, team identities, events, artifacts and approvals."""

    # Single source of truth: state_machine_def.py (merged Track 1 + Track 2).
    TRANSITIONS: Dict[str, Set[str]] = _SHARED_TRANSITIONS

    def __init__(self) -> None:
        self.agents: Dict[str, AgentIdentity] = {}
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.topologies: Dict[str, TeamTopology] = {}
        self.tasks: Dict[str, TaskRecord] = {}
        self.events: List[Event] = []
        self.artifacts: Dict[str, Artifact] = {}
        self.evidence: Dict[str, Evidence] = {}
        self.approvals: Dict[str, Dict[str, Any]] = {}

    def register_agent(self, identity: AgentIdentity) -> None:
        if identity.agent_id in self.agents:
            raise ValueError("duplicate agent identity: %s" % identity.agent_id)
        self.agents[identity.agent_id] = identity

    def register_skill(self, skill_id: str, manifest: Dict[str, Any]) -> None:
        if skill_id in self.skills:
            raise ValueError("duplicate skill: %s" % skill_id)
        self.skills[skill_id] = manifest

    def register_topology(self, topology: TeamTopology) -> None:
        unknown = [node for node in topology.nodes if node not in self.agents]
        if unknown:
            raise ValueError("topology references unknown agents: %s" % ", ".join(unknown))
        self.topologies[topology.team_id] = topology

    def create_task(self, task_id: str, domain: str, input_payload: Dict[str, Any], trace_id: Optional[str] = None) -> TaskRecord:
        if task_id in self.tasks:
            raise ValueError("duplicate task: %s" % task_id)
        task = TaskRecord(task_id, trace_id or new_id("trace"), domain, input_payload, "RECEIVED")
        self.tasks[task_id] = task
        self._event(task, "TASK_CREATED", "control-plane", {"domain": domain, "input_digest": digest(input_payload)})
        return task

    def _event(self, task: TaskRecord, event_type: str, actor: str, payload: Dict[str, Any]) -> Event:
        event = Event(new_id("evt"), task.task_id, task.trace_id, event_type, actor, payload, task.state_version)
        self.events.append(event)
        return event

    def transition(self, task_id: str, target: str, actor: str, reason: str, metadata: Optional[Dict[str, Any]] = None, expected_state_version: Optional[int] = None) -> TaskRecord:
        task = self.tasks[task_id]
        if expected_state_version is not None and task.state_version != expected_state_version:
            raise ConcurrentStateError("expected state version %d, found %d" % (expected_state_version, task.state_version))
        allowed = self.TRANSITIONS.get(task.state, set())
        if target not in allowed:
            raise StateTransitionError("%s -> %s is not allowed" % (task.state, target))
        if actor not in {"control-plane", "AgentTeamsControlPlane"}:
            identity = self.agents.get(actor)
            if identity is None:
                raise AuthorizationError("unknown transition actor: %s" % actor)
            if target not in identity.allowed_states:
                raise AuthorizationError("%s cannot own target state %s" % (actor, target))
        previous = task.state
        task.state = target
        task.state_version += 1
        task.updated_at = utc_now()
        if metadata:
            task.metadata.update(metadata)
        self._event(task, "STATE_TRANSITION", actor, {"from": previous, "to": target, "reason": reason, "metadata": metadata or {}})
        return task

    def publish_artifact(self, task_id: str, artifact_type: str, producer: str, payload: Dict[str, Any], evidence_refs: Optional[List[str]] = None, schema_version: str = "1.0") -> Artifact:
        task = self.tasks[task_id]
        artifact = Artifact(new_id("art"), task_id, task.trace_id, artifact_type, schema_version, producer, payload, evidence_refs or [])
        self.artifacts[artifact.artifact_id] = artifact
        self._event(task, "ARTIFACT_PUBLISHED", producer, {"artifact_id": artifact.artifact_id, "artifact_type": artifact_type, "evidence_refs": artifact.evidence_refs})
        return artifact

    def record_evidence(self, task_id: str, kind: str, label: str, source: str, content: Any) -> Evidence:
        task = self.tasks[task_id]
        item = Evidence(new_id("ev"), task_id, task.trace_id, kind, label, source, content, digest(content))
        self.evidence[item.evidence_id] = item
        self._event(task, "EVIDENCE_RECORDED", source, {"evidence_id": item.evidence_id, "kind": kind, "label": label, "content_digest": item.content_digest})
        return item

    def request_approval(self, task_id: str, actor: str, scope: Dict[str, Any], expected_state: Optional[str] = None) -> str:
        task = self.tasks[task_id]
        approval_id = new_id("approval")
        scope_digest = digest(scope)
        self.approvals[approval_id] = {
            "approval_id": approval_id,
            "task_id": task_id,
            "trace_id": task.trace_id,
            "requested_by": actor,
            "scope": scope,
            "scope_digest": scope_digest,
            "requested_state": task.state,
            "requested_state_version": task.state_version,
            "expected_state": expected_state,
            "status": "PENDING",
            "created_at": utc_now(),
        }
        self._event(task, "APPROVAL_REQUESTED", actor, {"approval_id": approval_id, "scope": scope, "scope_digest": scope_digest, "expected_state": expected_state})
        return approval_id

    def approve(self, approval_id: str, reviewer: str, decision: str = "APPROVED", note: str = "", decision_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        approval = self.approvals[approval_id]
        if approval["status"] != "PENDING":
            raise ApprovalError("approval is not pending")
        if decision not in {"APPROVED", "REJECTED"}:
            raise ApprovalError("decision must be APPROVED or REJECTED")
        task = self.tasks[approval["task_id"]]
        if approval.get("expected_state") and task.state != approval["expected_state"]:
            raise ApprovalError("approval expected task state %s, found %s" % (approval["expected_state"], task.state))
        evidence = dict(decision_evidence or {})
        evidence.setdefault("provider", "local-conformance")
        evidence.setdefault("reviewer_identity", reviewer)
        evidence.setdefault("scope_digest", approval["scope_digest"])
        evidence.setdefault("event_id", new_id("approval_evt"))
        if evidence["reviewer_identity"] != reviewer:
            raise ApprovalError("reviewer identity does not match the approval actor")
        if evidence["scope_digest"] != approval["scope_digest"]:
            raise ApprovalError("approval scope digest does not match the requested scope")
        approval.update({"status": decision, "reviewer": reviewer, "note": note, "decision_evidence": evidence, "decided_at": utc_now()})
        self._event(task, "APPROVAL_DECIDED", reviewer, {"approval_id": approval_id, "decision": decision, "note": note, "scope_digest": approval["scope_digest"], "decision_evidence": evidence})
        return approval

    def checkpoint_payload(self, task_id: str) -> Dict[str, Any]:
        task = self.tasks[task_id]
        return {"task": asdict(task), "events": [asdict(e) for e in self.events if e.task_id == task_id], "artifacts": [asdict(a) for a in self.artifacts.values() if a.task_id == task_id], "evidence": [asdict(e) for e in self.evidence.values() if e.task_id == task_id], "approvals": [a for a in self.approvals.values() if a["task_id"] == task_id]}

    def trace(self, task_id: str) -> List[Dict[str, Any]]:
        return [asdict(e) for e in self.events if e.task_id == task_id]

    def evidence_pack(self, task_id: str) -> Dict[str, Any]:
        task = self.tasks[task_id]
        return {"task_id": task_id, "trace_id": task.trace_id, "domain": task.domain, "input_payload": task.input_payload, "state": task.state, "state_version": task.state_version, "artifacts": [asdict(a) for a in self.artifacts.values() if a.task_id == task_id], "evidence": [asdict(e) for e in self.evidence.values() if e.task_id == task_id], "approvals": [a for a in self.approvals.values() if a["task_id"] == task_id], "trace": self.trace(task_id), "topologies": [asdict(topology) for topology in self.topologies.values()]}


class SQLiteCheckpointProvider:
    """Checkpoint storage only; it never owns task state transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.path)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (task_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")

    def save(self, task_id: str, state_version: int, payload: Dict[str, Any]) -> None:
        with sqlite3.connect(str(self.path)) as conn:
            conn.execute("INSERT OR REPLACE INTO checkpoints(task_id, state_version, payload, updated_at) VALUES (?, ?, ?, ?)", (task_id, state_version, canonical_json(payload), utc_now()))

    def load(self, task_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(str(self.path)) as conn:
            row = conn.execute("SELECT state_version, payload, updated_at FROM checkpoints WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return {"state_version": row[0], "payload": json.loads(row[1]), "updated_at": row[2]}


class LocalEvidenceProvider:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, task_id: str) -> Path:
        return self.root / (task_id + ".json")

    def write_pack(self, task_id: str, pack: Dict[str, Any]) -> Path:
        path = self.path_for(task_id)
        pack["evidence_pack_path"] = str(path)
        pack["evidence_pack_relative_path"] = "evidence/" + path.name
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


PORT_MANIFESTS: List[Dict[str, Any]] = [
    {"port_id": "CodeExecutionPort", "plane": "Runtime", "contract": ["execute", "inspect", "cancel"], "local_provider": "fixture-local", "alternate_provider": "opencode", "cloud_provider": "pending-verification"},
    {"port_id": "WorkspacePort", "plane": "Runtime", "contract": ["create", "snapshot", "restore", "destroy"], "local_provider": "filesystem", "cloud_provider": "pending-verification"},
    {"port_id": "StateCheckpointPort", "plane": "Runtime", "contract": ["save", "load", "compare-and-swap"], "local_provider": "sqlite", "cloud_provider": "pending-verification"},
    {"port_id": "LeaseRecoveryPort", "plane": "Runtime", "contract": ["acquire", "renew", "fence", "release"], "local_provider": "file-lock", "cloud_provider": "pending-verification"},
    {"port_id": "EventBusPort", "plane": "Runtime", "contract": ["publish", "subscribe", "ack"], "local_provider": "in-memory", "cloud_provider": "pending-verification"},
    {"port_id": "ArtifactEvidencePort", "plane": "Tool & Evidence", "contract": ["put", "get", "list", "digest"], "local_provider": "filesystem", "cloud_provider": "pending-verification"},
    {"port_id": "KnowledgeMemoryPort", "plane": "Tool & Evidence", "contract": ["search", "upsert", "delete"], "local_provider": "json-index", "cloud_provider": "pending-verification"},
    {"port_id": "SCMPort", "plane": "Tool & Evidence", "contract": ["diff", "branch", "commit", "revert"], "local_provider": "git", "cloud_provider": "pending-verification"},
    {"port_id": "CIPort", "plane": "Tool & Evidence", "contract": ["run", "status", "logs", "cancel"], "local_provider": "subprocess", "cloud_provider": "pending-verification"},
    {"port_id": "PolicyGuardPort", "plane": "Governance", "contract": ["check", "explain", "audit"], "local_provider": "deterministic-rules", "cloud_provider": "pending-verification"},
    {"port_id": "ApprovalHITLPort", "plane": "Governance", "contract": ["request", "approve", "reject", "resume"], "local_provider": "console", "cloud_provider": "pending-verification"},
    {"port_id": "SecretPort", "plane": "Governance", "contract": ["resolve", "rotate", "audit"], "local_provider": "environment", "cloud_provider": "pending-verification"},
    {"port_id": "ConfigRegistryPort", "plane": "Governance", "contract": ["get", "watch", "version"], "local_provider": "yaml", "cloud_provider": "pending-verification"},
    {"port_id": "ModelGatewayPort", "plane": "Model & Observability", "contract": ["complete", "embed", "health"], "local_provider": "direct-sdk", "cloud_provider": "pending-verification"},
    {"port_id": "ObservabilityPort", "plane": "Model & Observability", "contract": ["trace", "metric", "log", "export"], "local_provider": "jsonl", "cloud_provider": "pending-verification"},
]


class CodeExecutionProvider:
    provider_id = "abstract"

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class CIPort:
    """Independent verification contract.

    Code execution providers return changes and workspace references only.
    Verification results must be produced by a separate runner so an
    executor cannot make its own patch authoritative by reporting "pass".
    """

    provider_id = "abstract-ci"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


def _run_test_suite(workspace: Path, suite: str) -> Dict[str, Any]:
    environment = os.environ.copy()
    python_path = str(workspace / "src")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = python_path
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", suite, "-v"],
            cwd=str(workspace),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        return {"status": "fail", "returncode": None, "output": str(error)[:4000]}
    output = (result.stdout + "\n" + result.stderr)[-4000:]
    return {"status": "pass" if result.returncode == 0 else "fail", "returncode": result.returncode, "output": output}


class LocalSubprocessCIPort(CIPort):
    """Run verification from an executor-independent subprocess boundary."""

    provider_id = "subprocess-ci"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        workspace = Path(str(task["workspace"]))
        verifier_workspace = Path(str(task["verifier_workspace"]))
        if not workspace.is_dir() or not verifier_workspace.is_dir():
            return {"provider": self.provider_id, "status": "fail", "failure_signature": "VERIFIER_WORKSPACE_UNAVAILABLE"}
        public = _run_test_suite(workspace, task.get("public_suite", "tests"))
        hidden = _run_test_suite(verifier_workspace, task.get("hidden_suite", "hidden_tests"))
        failure_signature = None
        if public["status"] != "pass":
            failure_signature = "PUBLIC_CHECK_FAILED"
        elif hidden["status"] != "pass":
            failure_signature = "REGRESSION_TIMEOUT_GUARD"
        return {
            "provider": self.provider_id,
            "status": "pass" if failure_signature is None else "fail",
            "public": public["status"],
            "hidden": hidden["status"],
            "failure_signature": failure_signature,
            "public_output": public["output"],
            "hidden_output": hidden["output"],
        }


class DeterministicCIPort(CIPort):
    """Independent CI oracle for providers that intentionally run dry-run mode."""

    provider_id = "deterministic-ci"

    def __init__(self, fail_first: bool = True) -> None:
        self.fail_first = fail_first

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        attempt = int(task.get("attempt", 1))
        failed = self.fail_first and attempt == 1
        return {
            "provider": self.provider_id,
            "status": "fail" if failed else "pass",
            "public": "pass",
            "hidden": "fail" if failed else "pass",
            "failure_signature": "REGRESSION_TIMEOUT_GUARD" if failed else None,
            "mode": "deterministic-ci-oracle",
        }


class WorkspaceRequiredCIPort(CIPort):
    """Fail closed when a live executor did not expose a verifiable workspace."""

    provider_id = "workspace-required-ci"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.provider_id,
            "status": "fail",
            "public": "unknown",
            "hidden": "unknown",
            "failure_signature": "VERIFIER_WORKSPACE_UNAVAILABLE",
            "reason": "live execution did not provide an independent verifier workspace",
        }


class ScriptedCodeExecutionProvider(CodeExecutionProvider):
    provider_id = "scripted-local"

    def __init__(self, fail_first: bool = True) -> None:
        self.fail_first = fail_first

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        attempt = int(task.get("attempt", 1))
        if self.fail_first and attempt == 1:
            return {"provider": self.provider_id, "attempt": attempt, "status": "PATCHED", "patch": "fix timeout guard"}
        return {"provider": self.provider_id, "attempt": attempt, "status": "PATCHED", "patch": "fix timeout guard and add idempotent retry"}


class FixtureCodeExecutionProvider(CodeExecutionProvider):
    """Execute the Track 1 fixture in an isolated local workspace.

    This provider is deterministic, but it performs real file changes and
    subprocess test runs. It is the bridge between the local conformance
    runtime and a future hosted CodeExecutionPort provider.
    """

    provider_id = "fixture-local"

    def __init__(self, workspace_root: Path, fixture_root: Path) -> None:
        self.workspace_root = workspace_root
        self.fixture_root = fixture_root

    def _workspace(self, task: Dict[str, Any]) -> Path:
        workspace_id = str(task.get("workspace_id", "track1-codeops-demo"))
        if Path(workspace_id).name != workspace_id or workspace_id in {"", ".", ".."}:
            raise ValueError("workspace_id must be a single safe path component")
        return self.workspace_root / workspace_id

    def _verifier_workspace(self, workspace: Path) -> Path:
        return self.workspace_root.parent / "verifier_workspaces" / workspace.name

    def _prepare(self, workspace: Path) -> None:
        if workspace.exists():
            shutil.rmtree(workspace)
        verifier = self._verifier_workspace(workspace)
        if verifier.exists():
            shutil.rmtree(verifier)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        verifier.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.fixture_root, workspace, ignore=shutil.ignore_patterns("hidden_tests"))
        shutil.copytree(self.fixture_root, verifier)

    @staticmethod
    def _apply_patch(workspace: Path, attempt: int) -> str:
        path = workspace / "src" / "retry_guard.py"
        source = path.read_text(encoding="utf-8")
        if attempt == 1:
            old = ("    for _ in range(attempts):\n"
                   "        try:\n"
                   "            return operation(timeout_budget, idempotency_key)\n")
            new = ("    deadline = time.monotonic() + timeout_budget\n\n"
                   "    for _ in range(attempts):\n"
                   "        remaining = max(0.0, deadline - time.monotonic())\n"
                   "        try:\n"
                   "            return operation(remaining, idempotency_key)\n")
            if old not in source:
                raise ValueError("attempt 1 patch target was not found")
            path.write_text(source.replace(old, new), encoding="utf-8")
            return "carry total timeout budget"

        old = "        except TimeoutError:\n            continue\n"
        new = ("        except TimeoutError:\n"
               "            if idempotency_key is not None:\n"
               "                raise\n"
               "            continue\n")
        if old not in source:
            raise ValueError("attempt 2 patch target was not found")
        path.write_text(source.replace(old, new), encoding="utf-8")
        return "add idempotency guard for ambiguous timeout"

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        attempt = int(task.get("attempt", 1))
        if attempt < 1:
            raise ValueError("attempt must be positive")
        approved_scope = set(task.get("approved_scope", []))
        if "src/retry_guard.py" not in approved_scope:
            raise ValueError("approved scope does not include src/retry_guard.py")

        workspace = self._workspace(task)
        if attempt == 1:
            self._prepare(workspace)
        elif not workspace.is_dir() or not self._verifier_workspace(workspace).is_dir():
            raise FileNotFoundError("workspace must be prepared by attempt 1")
        patch = self._apply_patch(workspace, attempt)
        verifier_source = self._verifier_workspace(workspace) / "src" / "retry_guard.py"
        verifier_source.write_text((workspace / "src" / "retry_guard.py").read_text(encoding="utf-8"), encoding="utf-8")
        return {
            "provider": self.provider_id,
            "attempt": attempt,
            "status": "PATCHED",
            "mode": "real-fixture-subprocess",
            "workspace": str(workspace),
            "verifier_workspace": str(self._verifier_workspace(workspace)),
            "changed_files": ["src/retry_guard.py"],
            "patch": patch,
        }


class OpencodeCodeExecutionProvider(CodeExecutionProvider):
    """Adapter boundary for the installed opencode CLI.

    Default mode is deterministic dry-run so tests do not require a network or
    model credential. GOAI_OPENCODE_LIVE=1 enables a future live invocation.
    """

    provider_id = "opencode"

    def __init__(self, executable: Optional[str] = None, live: bool = False) -> None:
        self.executable = executable or shutil.which("opencode") or "opencode"
        self.live = live or os.getenv("GOAI_OPENCODE_LIVE") == "1"

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        attempt = int(task.get("attempt", 1))
        if self.live:
            prompt = task.get("prompt", "Inspect the task and propose a safe patch.")
            result = subprocess.run([self.executable, "run", prompt, "--no-replay"], capture_output=True, text=True, timeout=120)
            return {"provider": self.provider_id, "attempt": attempt, "status": "PATCHED" if result.returncode == 0 else "FAILED", "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:], "returncode": result.returncode, "workspace": task.get("workspace")}
        if attempt == 1:
            return {"provider": self.provider_id, "attempt": attempt, "status": "PATCHED", "mode": "deterministic-adapter-dry-run", "patch": "fix timeout guard"}
        return {"provider": self.provider_id, "attempt": attempt, "status": "PATCHED", "mode": "deterministic-adapter-dry-run", "patch": "fix timeout guard and add idempotent retry"}


def ci_port_for(provider: CodeExecutionProvider, fail_first: bool = True) -> CIPort:
    if isinstance(provider, FixtureCodeExecutionProvider):
        return LocalSubprocessCIPort()
    if isinstance(provider, OpencodeCodeExecutionProvider) and provider.live:
        return WorkspaceRequiredCIPort()
    return DeterministicCIPort(fail_first=fail_first)


def provider_by_id(provider_id: str, **options: Any) -> CodeExecutionProvider:
    if provider_id == "opencode":
        return OpencodeCodeExecutionProvider(executable=options.get("executable"), live=options.get("live", False))
    if provider_id == "scripted-local":
        return ScriptedCodeExecutionProvider(fail_first=options.get("fail_first", True))
    if provider_id == "fixture-local":
        return FixtureCodeExecutionProvider(options["workspace_root"], options["fixture_root"])
    raise ValueError("unknown code provider: %s" % provider_id)
