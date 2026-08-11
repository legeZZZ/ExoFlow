"""M1 Trace-to-Skill: trajectory distillation machinery.

Design basis: Trace2Skill (arXiv:2603.25158). Lessons are not applied to the
skill library one trajectory at a time (sequential online updates fragment
skills and overfit trajectory-local quirks). Instead:

- Stage A: closed tasks' Evidence Packs accumulate in a trace pool, tagged by
  domain / verdict / failure signature;
- Stage B: once enough traces are pooled, two parallel analyst perspectives
  (success patterns / failure guards) each propose patches to the target
  skill;
- Stage C: patches merge into the single consolidated skill document under
  programmatic conflict detection and format validation, then pass the
  sensitive-info/license scan, fidelity/generalization/counterexample checks,
  human review, and versioned publish with rollback.

The P1 vertical slice keeps analysis deterministic (heuristic, replayable in
tests); an LLM-backed analyst plugs into ``propose_patches`` later without
changing pool/merge/gate/publish semantics.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "m1-trace-to-skill/1.0"


class DistillError(Exception):
    """Raised when distillation inputs or gates fail."""


# --- Stage A: trace pool ------------------------------------------------------


class TracePool:
    """Filesystem-backed pool of distilled-ready Evidence Packs."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def ingest(self, evidence_pack: Dict[str, Any]) -> Dict[str, Any]:
        task = evidence_pack.get("task") or {}
        task_id = task.get("task_id")
        if not task_id:
            raise DistillError("EVIDENCE_PACK_TASK_ID_MISSING")
        artifacts = evidence_pack.get("artifacts") or []
        verdicts = [
            (a.get("payload") or {}).get("verdict")
            for a in artifacts
            if a.get("artifact_type") == "VerificationReport"
        ]
        final_verdict = verdicts[-1] if verdicts else None
        signatures = sorted(
            {
                (a.get("payload") or {}).get("failure_signature")
                for a in artifacts
                if (a.get("payload") or {}).get("failure_signature")
            }
        )
        record = {
            "schema": SCHEMA_VERSION,
            "task_id": task_id,
            "domain": task.get("domain", "unknown"),
            "final_state": task.get("state"),
            "state_version": task.get("state_version"),
            "tags": {
                "domain": task.get("domain", "unknown"),
                "verdict": final_verdict,
                "failure_signatures": signatures,
            },
            "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "evidence_pack": evidence_pack,
        }
        path = self.root / ("%s.json" % task_id)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
        return record

    def list(self) -> List[Dict[str, Any]]:
        records = []
        for path in sorted(self.root.glob("*.json")):
            records.append(json.loads(path.read_text()))
        return records

    def by_domain(self, domain: str) -> List[Dict[str, Any]]:
        return [r for r in self.list() if r["tags"]["domain"] == domain]


# --- Stage B: dual-perspective patch proposal ---------------------------------


@dataclass(frozen=True)
class SkillPatch:
    """A candidate patch against one consolidated skill document."""

    target_skill: str
    kind: str  # "pattern" (do) or "guard" (avoid)
    title: str
    content: str
    source_traces: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target_skill": self.target_skill,
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "source_traces": list(self.source_traces),
        }


def _events_of(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (record.get("evidence_pack") or {}).get("events") or []


def _artifacts_of(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (record.get("evidence_pack") or {}).get("artifacts") or []


def propose_success_patches(records: Sequence[Dict[str, Any]], target_skill: str) -> List[SkillPatch]:
    """Success analyst: distill effective patterns from PASS trajectories."""
    patches: List[SkillPatch] = []
    passed = [r for r in records if r["tags"].get("verdict") == "PASS"]
    if not passed:
        return patches
    chains = set()
    for record in passed:
        chain = tuple(
            e.get("artifact_type")
            for e in _events_of(record)
            if e.get("event_type") == "ARTIFACT_PUBLISHED"
        )
        if chain:
            chains.add(chain)
    if chains:
        canonical = sorted(chains)[0]
        patches.append(
            SkillPatch(
                target_skill=target_skill,
                kind="pattern",
                title="PASS 轨迹的标准产物序列",
                content="按此顺序产出 Artifact 的轨迹均通过独立验证：" + " → ".join(canonical),
                source_traces=tuple(sorted(r["task_id"] for r in passed)),
            )
        )
    verified = [r for r in passed if any(a.get("artifact_type") == "VerificationReport" for a in _artifacts_of(r))]
    if verified:
        patches.append(
            SkillPatch(
                target_skill=target_skill,
                kind="pattern",
                title="独立验证先行",
                content="PASS 轨迹中 VerificationReport 均在验证态内写入且含 commands/verifier_context；保持独立工作区取证。",
                source_traces=tuple(sorted(r["task_id"] for r in verified)),
            )
        )
    return patches


def propose_failure_patches(records: Sequence[Dict[str, Any]], target_skill: str) -> List[SkillPatch]:
    """Failure analyst: distill prevention guards from failed trajectories."""
    patches: List[SkillPatch] = []
    failed = [r for r in records if r["tags"].get("verdict") == "FAIL" or r["tags"].get("failure_signatures")]
    if not failed:
        return patches
    signature_sources: Dict[str, List[str]] = {}
    for record in failed:
        for signature in record["tags"].get("failure_signatures") or []:
            signature_sources.setdefault(signature, []).append(record["task_id"])
    for signature, sources in sorted(signature_sources.items()):
        patches.append(
            SkillPatch(
                target_skill=target_skill,
                kind="guard",
                title="防错：%s" % signature[:48],
                content="失败签名 %s 已在 %d 条轨迹出现（%s）；执行前检查对应前置条件，命中即停并升级。"
                % (signature, len(sources), ", ".join(sorted(sources))),
                source_traces=tuple(sorted(sources)),
            )
        )
    escalations = [
        r
        for r in records
        if any(
            e.get("event_type") == "STATE_TRANSITION" and "NEEDS_HUMAN" in json.dumps(e.get("payload") or {})
            for e in _events_of(r)
        )
    ]
    if escalations:
        patches.append(
            SkillPatch(
                target_skill=target_skill,
                kind="guard",
                title="防错：证据不足先升级",
                content="存在转人工轨迹；证据不足时提前升级 NEEDS_HUMAN，不得降低验证标准强行推进。",
                source_traces=tuple(sorted(r["task_id"] for r in escalations)),
            )
        )
    return patches


def propose_patches(records: Sequence[Dict[str, Any]], target_skill: str) -> List[SkillPatch]:
    """Parallel dual-perspective analysis (deterministic P1 implementation)."""
    return propose_success_patches(records, target_skill) + propose_failure_patches(records, target_skill)


# --- Stage C: conflict-free consolidation -------------------------------------

SKILL_REQUIRED_SECTIONS: Tuple[str, ...] = ("## 职责", "## 流程", "## 硬规则")


def validate_skill_document(document: str) -> List[str]:
    """Format validation for the consolidated skill document."""
    errors = []
    for section in SKILL_REQUIRED_SECTIONS:
        if section not in document:
            errors.append("SKILL_SECTION_MISSING %s" % section)
    return errors


def _topic_key(title: str) -> str:
    return re.sub(r"^(防错：|PASS 轨迹的|独立)", "", title).strip()[:24]


def merge_patches(document: str, patches: Sequence[SkillPatch]) -> Tuple[str, List[str]]:
    """Merge patches into the consolidated skill document.

    Returns (merged_document, conflicts). Conflicts detected:
    - duplicate patch titles (same lesson proposed twice);
    - pattern/guard contradiction on the same topic key;
    - merged document failing format validation.
    """
    conflicts: List[str] = []
    seen_titles: Dict[str, SkillPatch] = {}
    topics: Dict[str, set] = {}
    accepted: List[SkillPatch] = []
    for patch in patches:
        if patch.title in seen_titles:
            conflicts.append("DUPLICATE_PATCH %s" % patch.title)
            continue
        key = _topic_key(patch.title)
        kinds = topics.setdefault(key, set())
        if ("pattern" in kinds and patch.kind == "guard") or ("guard" in kinds and patch.kind == "pattern"):
            conflicts.append("CONTRADICTORY_PATCH %s (%s vs %s)" % (patch.title, patch.kind, "/".join(sorted(kinds))))
            continue
        kinds.add(patch.kind)
        seen_titles[patch.title] = patch
        accepted.append(patch)
    merged = document
    for patch in accepted:
        section = "## 流程" if patch.kind == "pattern" else "## 硬规则"
        entry = "\n- [%s] %s（来源：%s）" % (
            patch.title,
            patch.content,
            ",".join(patch.source_traces) or "pool",
        )
        if section in merged:
            merged = merged.replace(section, section + entry, 1)
        else:
            merged = merged.rstrip() + "\n\n%s%s\n" % (section, entry)
    conflicts.extend(validate_skill_document(merged))
    return merged, conflicts


# --- Gates: scan, evaluation, candidate lifecycle -----------------------------

SENSITIVE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("PRIVATE_KEY", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("BEARER_TOKEN", r"(?i)bearer\s+[a-z0-9_\-\.]{20,}"),
    ("HEX_SECRET", r"\b[a-f0-9]{64}\b"),
)

LICENSE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("GPL", r"(?i)\bGPL-?[23]\b"),
    ("AGPL", r"(?i)\bAGPL\b"),
    ("PROPRIETARY", r"(?i)all rights reserved"),
)


def scan_sensitive(text: str) -> List[str]:
    return ["SENSITIVE_%s" % name for name, pattern in SENSITIVE_PATTERNS if re.search(pattern, text)]


def scan_license(text: str) -> List[str]:
    return ["LICENSE_%s" % name for name, pattern in LICENSE_PATTERNS if re.search(pattern, text)]


def build_candidate(
    target_skill: str,
    patches: Sequence[SkillPatch],
    merged_document: str,
    source_traces: Sequence[str],
) -> Dict[str, Any]:
    """Assemble a SkillCandidate artifact payload (pre-review status)."""
    return {
        "schema": SCHEMA_VERSION,
        "target_skill": target_skill,
        "patches": [p.as_dict() for p in patches],
        "merged_document": merged_document,
        "source_traces": sorted(source_traces),
        "review_status": "draft",
        "evaluations": {},
    }


EvalFn = Callable[[Dict[str, Any]], List[str]]


def evaluate_candidate(
    candidate: Dict[str, Any],
    *,
    fidelity: Optional[EvalFn] = None,
    generalization: Optional[EvalFn] = None,
    counterexample: Optional[EvalFn] = None,
) -> Dict[str, Any]:
    """Run the three evaluation gates; each returns a list of failures ([]=pass).

    Default structural implementations are deterministic; verifier-workspace
    backed evaluations plug in as callables with the same signature.
    """
    candidate = dict(candidate)
    evaluations: Dict[str, Any] = {}
    document = candidate.get("merged_document", "")

    def default_fidelity(c: Dict[str, Any]) -> List[str]:
        missing = [p["title"] for p in c["patches"] if p["title"] not in document]
        return ["FIDELITY_PATCH_LOST %s" % t for t in missing]

    def default_generalization(c: Dict[str, Any]) -> List[str]:
        if not c.get("patches"):
            return ["GENERALIZATION_EMPTY_CANDIDATE"]
        return []

    def default_counterexample(c: Dict[str, Any]) -> List[str]:
        guards = [p for p in c["patches"] if p["kind"] == "guard"]
        patterns = [p for p in c["patches"] if p["kind"] == "pattern"]
        conflicts = []
        for guard in guards:
            key = _topic_key(guard["title"])
            if any(key and key in p["title"] for p in patterns):
                conflicts.append("COUNTEREXAMPLE_KILL %s" % guard["title"])
        return conflicts

    for name, fn, default in (
        ("fidelity", fidelity, default_fidelity),
        ("generalization", generalization, default_generalization),
        ("counterexample", counterexample, default_counterexample),
    ):
        failures = (fn or default)(candidate)
        evaluations[name] = {"pass": not failures, "failures": failures}
    candidate["evaluations"] = evaluations
    candidate["review_status"] = (
        "evaluation_passed"
        if all(item["pass"] for item in evaluations.values())
        else "evaluation_failed"
    )
    return candidate


def record_human_review(candidate: Dict[str, Any], approved: bool, reviewer: str, note: str = "") -> Dict[str, Any]:
    if candidate.get("review_status") != "evaluation_passed":
        raise DistillError("REVIEW_REQUIRES_EVALUATION_PASSED")
    candidate = dict(candidate)
    candidate["review_status"] = "approved" if approved else "rejected"
    candidate["review"] = {"reviewer": reviewer, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return candidate


# --- Publish: versioned skill matrix with rollback -----------------------------


def publish(matrix_path: Path | str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Publish an approved candidate into the skill matrix (version + 1)."""
    if candidate.get("review_status") != "approved":
        raise DistillError("PUBLISH_REQUIRES_APPROVED_CANDIDATE")
    path = Path(matrix_path)
    matrix = json.loads(path.read_text()) if path.exists() else {"schema": SCHEMA_VERSION, "skills": {}}
    skills = matrix.setdefault("skills", {})
    entry = skills.setdefault(candidate["target_skill"], {"current_version": 0, "history": []})
    next_version = entry["current_version"] + 1
    entry["history"].append(
        {
            "version": next_version,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "patches": candidate["patches"],
            "source_traces": candidate["source_traces"],
            "evaluations": candidate["evaluations"],
            "review": candidate.get("review"),
        }
    )
    entry["current_version"] = next_version
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True))
    return matrix


def rollback(matrix_path: Path | str, target_skill: str, to_version: int) -> Dict[str, Any]:
    """Roll a skill back to a previously published version."""
    path = Path(matrix_path)
    matrix = json.loads(path.read_text())
    entry = matrix.get("skills", {}).get(target_skill)
    if not entry:
        raise DistillError("SKILL_NOT_PUBLISHED %s" % target_skill)
    if not any(item["version"] == to_version for item in entry["history"]):
        raise DistillError("VERSION_NOT_FOUND %s@%d" % (target_skill, to_version))
    entry["current_version"] = to_version
    entry.setdefault("rollbacks", []).append(
        {"to_version": to_version, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    )
    path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True))
    return matrix


# --- End-to-end convenience -----------------------------------------------------


def distill(
    pool: TracePool,
    target_skill: str,
    base_document: str,
    *,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """Run stage B + C over the pool and return an evaluated candidate."""
    records = pool.by_domain(domain) if domain else pool.list()
    if not records:
        raise DistillError("TRACE_POOL_EMPTY")
    patches = propose_patches(records, target_skill)
    merged, conflicts = merge_patches(base_document, patches)
    hard_conflicts = [c for c in conflicts if c.startswith(("DUPLICATE_PATCH", "CONTRADICTORY_PATCH"))]
    candidate = build_candidate(target_skill, patches, merged, [r["task_id"] for r in records])
    candidate["consolidation_conflicts"] = conflicts
    scan_hits = scan_sensitive(merged) + scan_license(merged)
    candidate["scan"] = {"pass": not scan_hits, "hits": scan_hits}
    if hard_conflicts or scan_hits:
        candidate["review_status"] = "blocked"
        return candidate
    return evaluate_candidate(candidate)
