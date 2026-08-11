# ExoFlow

[中文](README.zh-CN.md)

**Multi-agent software engineering orchestration with a deterministic, typed, and auditable state machine core.**

ExoFlow coordinates 9 specialist AI agents through a CAS-guarded state machine to triage
incidents, locate root causes, execute verified patches, and distill operational knowledge —
all while maintaining a cryptographically verifiable event chain.

## Table of Contents

- [Why ExoFlow?](#why-exoflow)
- [Architecture](#architecture)
- [Core Components](#core-components)
  - [State Machine](#state-machine)
  - [Native MCP Server](#native-mcp-server)
  - [Skill Distillation](#skill-distillation)
  - [Agent Identity & Authorization](#agent-identity--authorization)
  - [Port Abstraction Layer](#port-abstraction-layer)
- [Tracks](#tracks)
  - [Track 1 — CodeOps Control Tower](#track-1--codeops-control-tower)
  - [Track 2 — Causal Growth Attribution](#track-2--causal-growth-attribution)
- [Quick Start](#quick-start)
- [Package Structure](#package-structure)
- [Requirements](#requirements)
- [License](#license)

## Why ExoFlow?

Most multi-agent frameworks let LLMs drive control flow through unstructured prompts.
ExoFlow inverts this: **the state machine is the single source of truth**, and agents
must operate within typed, verifiable boundaries.

| Capability | How ExoFlow Handles It |
|---|---|
| **State integrity** | CAS-guarded transitions; no agent can skip or fabricate states |
| **Authorization** | Per-actor state ownership — a Verifier cannot approve its own patches |
| **Auditability** | SQLite WAL event store records every transition, artifact, and approval |
| **Failure isolation** | Circuit breaker on repeated failure signatures → forced human escalation |
| **Knowledge retention** | 3-stage skill distillation pipeline from closed task trajectories |
| **Causal safety** | Causal gates prevent claims when data is observational or insufficient |
| **Zero dependencies** | Pure Python stdlib; installable offline with no network |
| **Vendor-neutral ports** | 15 abstract ports with swappable local/cloud providers |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Native MCP Server                        │
│  12 tools · CAS transition · artifact gate · approval HITL  │
│  side-effect ledger · evidence pack validation              │
└─────────────────────┬───────────────────────────────────────┘
                      │  typed events + artifacts
┌─────────────────────▼───────────────────────────────────────┐
│                    State Machine                             │
│  Track 1: 21 states, 25 transition rules                    │
│  Track 2: 19 states, 21 transition rules                    │
│  Artifact lifecycle x 9 types · actor ownership x 10 roles  │
│  Failure breaker x threshold 3 · transition preconditions   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│                     │                   │                   │
│  ┌──────────┐  ┌────▼─────┐  ┌──────────▼──────┐          │
│  │  Intake   │  │  Triage   │  │  Repo Analyst   │  ...     │
│  │  Worker   │  │  Worker   │  │  Worker         │          │
│  └──────────┘  └───────────┘  └─────────────────┘          │
│                                                              │
│  9 specialist agents · typed SKILL manifests · eval gates    │
└──────────────────────────────────────────────────────────────┘
```

## Core Components

### State Machine

The state machine (`state_machine_def.py`) is the single source of truth. Every
consumer — the local control plane, the native SQLite authority, and the Worker
package oracle — derives from this one file. A conformance test pins them together.

**Track 1 standard path (19-step code fix pipeline):**

```
RECEIVED → FUSED → TRIAGED → BOOTSTRAPPED → LOCATED → PLANNED
→ AWAITING_APPROVAL → PATCHED → VERIFYING → RELEASE_READY
→ POSTMORTEM → SKILL_DISTILLING → CLOSED
```

**Read-only analysis branch (no code changes):**

```
LOCATED → READONLY_VERIFYING → READONLY_VERIFIED → EVIDENCE_PACKED → CLOSED
```

Key guardrails:
- **Transition preconditions** — e.g., `PATCHED → VERIFYING` requires a `PatchBundle`
  artifact; `VERIFYING → RELEASE_READY` requires a `VerificationReport` with
  `verdict=PASS` written at the current state version.
- **Artifact state gates** — a `VerificationReport` can only be published during
  `VERIFYING` or `READONLY_VERIFYING`; writing it from any other state is rejected.
- **Failure signature circuit breaker** — 3 VerificatioReports with the same
  `failure_signature` blocks re-entry to verification states, forcing `NEEDS_HUMAN`.
- **Recovery** — crash-recovery paths via `RECOVERING` state, preserving version
  so the agent resumes from the exact breakpoint.

### Native MCP Server

A transactional, single-writer state authority (`native_mcp.py`) exposing **12 MCP
tools** over streamable HTTP (port 8780). Built on SQLite with WAL mode for
concurrent-read/single-write safety.

| Tool | Description |
|---|---|
| `task_create` | Idempotent task creation (only Leader) |
| `task_get` | Read authoritative task state |
| `state_transition` | CAS-guarded transition with actor authorization |
| `state_describe` | Agent workstation contract — available inputs, owned transitions, exit criteria, breaker status |
| `artifact_put` | Publish typed artifact at exact state version |
| `approval_request` | Create scope-bound human approval |
| `approval_decide` | Record Matrix-backed approval decision |
| `approval_status` | Read approval state |
| `evidence_pack` | Export full task event chain with optional validation replay |
| `side_effect_intent` | Query-ledger-before-execute — record external effect intent |
| `side_effect_result` | Record EXECUTED/FAILED/ROLLED_BACK outcome |
| `side_effect_list` | Recovery re-read of the side-effect ledger |

Every tool call is **actor-identity-gated** via bearer tokens. The authority
independently validates:
- The actor is authorized for the target state
- The state version matches (CAS — no stale writes)
- Required artifacts exist and pass verdict checks
- Approval scope is bound and not stale
- Failure signature breaker has not tripped

`evidence_pack(validate=true)` replays the entire event chain and re-derives every
digest — it trusts no field in the exported pack.

### Skill Distillation

Based on the Trace2Skill pattern (arXiv:2603.25158). Successful closed tasks feed
a 3-stage pipeline (`skill_distill.py`):

```
Stage A: Trace Pool
  └─ Evidence Packs ingested, tagged by domain/verdict/failure_signature

Stage B: Dual-Perspective Analysis
  ├─ Success-pattern analyst proposes patches (what worked)
  └─ Failure-guard analyst proposes patches (what broke + defense)

Stage C: Merge, Gate & Publish
  ├─ Programmatic conflict detection + format validation
  ├─ Sensitive-info and license scan
  ├─ Fidelity / generalization / counterexample checks
  ├─ Human review gate
  └─ Versioned publish with rollback support
```

The current implementation keeps Stage B deterministic (heuristic, replayable);
LLM-backed analysts plug into the same `propose_patches` interface later.

### Agent Identity & Authorization

Each agent has a typed identity defining exactly what it can do:

| Agent | Owned States | Produces |
|---|---|---|
| `codeops-intake` | `FUSED` | `IssueCluster` |
| `codeops-triage` | `TRIAGED` | `RiskAssessment` |
| `codeops-env-bootstrap` | `BOOTSTRAPPED` | `EnvironmentSnapshot` |
| `codeops-repo-analyst` | `LOCATED` | `RootCauseHypotheses` |
| `codeops-plan` | `PLANNED`, `AWAITING_APPROVAL` | `ChangePlan` |
| `codeops-executor` | `PATCHED`, `RECOVERING` | `PatchBundle` |
| `codeops-verifier` | `VERIFYING`, `RELEASE_READY`, `READONLY_VERIFYING`, `READONLY_VERIFIED`, `NEEDS_HUMAN` | `VerificationReport` |
| `codeops-postmortem` | `POSTMORTEM`, `SKILL_DISTILLING`, `CLOSED` | `Postmortem`, `SkillCandidate` |
| `codeops-lead` | `RECOVERING`, `NEEDS_HUMAN`, `EVIDENCE_PACKED`, `CLOSED` | — (coordination only) |

Key principle: **a Verifier cannot approve its own patches**. The executor publishes
`PatchBundle` but verification runs in an independent workspace with hidden tests,
and only the verifier can emit a `VerificationReport`.

### Port Abstraction Layer

15 abstract ports across 4 planes, each with swappable local and cloud providers:

| Plane | Ports |
|---|---|
| **Runtime** | `CodeExecutionPort`, `WorkspacePort`, `StateCheckpointPort`, `LeaseRecoveryPort`, `EventBusPort` |
| **Tool & Evidence** | `ArtifactEvidencePort`, `KnowledgeMemoryPort`, `SCMPort`, `CIPort` |
| **Governance** | `PolicyGuardPort`, `ApprovalHITLPort`, `SecretPort`, `ConfigRegistryPort` |
| **Model & Observability** | `ModelGatewayPort`, `ObservabilityPort` |

`CIPort` has special semantics: verification runs are always independent of the
code executor, so a patching agent can never make its own changes authoritative by
self-reporting "pass."

## Tracks

### Track 1 — CodeOps Control Tower

End-to-end incident-to-fix pipeline with 21 states and mandatory human approval:

1. **Intake** — Multi-source issue aggregation, dedup, `IssueCluster` artifact
2. **Triage** — Risk scoring, read-only vs. repair branch decision
3. **Env Bootstrap** — Read-only environment snapshot (no modifications)
4. **Repo Analyst** — Root cause hypotheses anchored to code locations
5. **Plan** — `ChangePlan` artifact, formal human approval request
6. **Approval Gate** — Scope-bound HITL with Matrix-backed evidence
7. **Executor** — Patch application within approved file scope only
8. **Verifier** — Independent workspace, public + hidden test suites
9. **Release** — Verification PASS confirmation
10. **Postmortem** — Retrospective archive, `SkillCandidate` generation
11. **Skill Distillation** — Approved candidate or explicit `NO_DISTILL_CONFIRMED`

The fixture demo (`run_demo.py`) exercises a concrete bug: a `retry_guard.py`
timeout budget defect. The first patch fixes the timeout but fails hidden
verification (`REGRESSION_TIMEOUT_GUARD`). The second patch adds idempotent retry
and passes.

### Track 2 — Causal Growth Attribution

Insurance analytics with 3 causal readiness cases:

| Case | Data Type | Outcome | Behavior |
|---|---|---|---|
| **A** | Observational | `DESCRIPTIVE_ONLY` | Shows co-movement, decomposition, pre-experiment draft; **no causal verbs** |
| **B** | Missing metadata | `DATA_INSUFFICIENT` | Fails closed, enumerates missing fields and remediation path |
| **C** | Randomized experiment | `CAUSAL_READY` | ITT estimate with 95% CI, guardrails, monitoring plan |

Process-isolated oracle benchmark measures causal-gate accuracy, false causal
assertion rate, refusal recall, effect error, and 95% CI coverage — without
exposing seeds, potential outcomes, or the oracle to the agent under test.

**Important**: This is a safety and reproducibility benchmark for the causal
simulator, not evidence of real-world insurance business uplift. The UCI Bank
Marketing dataset adapter (`track2_real_data.py`) pins SHA-256
`94a5cb4b7d461dab12f7f6123723054911fbdd28d84a2c4ec92378af019be686` and
fails closed on causal claims because the data has no randomized treatment.

## Quick Start

```bash
cd /path/to/exoflow

# Install (no dependencies beyond Python stdlib)
python3 -m pip install . --no-deps --no-build-isolation

# Run both track fixture demonstrations
PYTHONPATH=src python3 run_demo.py

# Run all tests
PYTHONPATH=src python3 -m unittest discover -s tests -v

# CLI entry points
python3 -m goai_control_tower --track track1 \
  --track1-input src/goai_control_tower/samples/track1/input.json

python3 -m goai_control_tower --track track2 --track2-benchmark --track2-benchmark-seeds 3

# Start the Native MCP state authority (streamable HTTP, port 8780)
CODEOPS_STATE_DATABASE=runtime_data/state.sqlite3 \
  python3 -m goai_control_tower.native_mcp --identity-file path/to/identities.json
```

## Package Structure

```text
ExoFlow/
├── src/goai_control_tower/
│   ├── state_machine_def.py     ← 30+ states, 9 artifact types, actor ownership
│   ├── native_mcp.py            ← 12-tool MCP server, SQLite WAL authority
│   ├── skill_distill.py         ← 3-stage trajectory distillation pipeline
│   ├── foundation.py            ← Control plane, 15 port manifests, CI providers
│   ├── track1.py                ← Track 1 execution: fixture + replay providers
│   ├── track2.py                ← Track 2 execution: 3 causal cases
│   ├── track2_analysis.py       ← Fixed-order log-chain decomposition
│   ├── track2_benchmark.py      ← Process-isolated oracle benchmark
│   ├── track2_datasets.py       ← Provenance-aware dataset catalog
│   ├── track2_real_data.py      ← UCI Bank Marketing adapter (SHA-256 pinned)
│   ├── track2_worker.py         ← Worker-side causal computation
│   ├── configuration.py         ← JSON config loader
│   ├── cli.py                   ← CLI entry point
│   └── samples/                 ← Input/output contract fixtures
├── packages/                    ← 9 Worker SKILL.md manifests + team-leader orchestrator
│   ├── team-leader/             ← State machine oracle for Workers (conformance-tested)
│   └── skills/                  ← 11 specialist skills, each with eval gates
│       ├── incident-memory/     ← Cross-task memory search
│       ├── issue-fusion/        ← Multi-source issue dedup
│       ├── judge-calibrator/    ← Evaluation consistency benchmark
│       ├── policy-check/        ← Policy compliance gate
│       ├── repo-map/            ← Codebase structure analysis
│       ├── resume-guard/        ← Resume/recovery safety
│       ├── risk-guard/          ← Risk assessment and scoring
│       ├── root-cause-probe/    ← Root cause localization
│       ├── runbook-rag/         ← Runbook retrieval-augmented generation
│       ├── safe-patch-exec/     ← Patch execution within approved scope
│       ├── skill-distiller/     ← Trace-to-skill distillation
│       └── verify-and-replay/   ← Verification and deterministic replay
├── tests/                       ← Unit test suite
├── run_demo.py                  ← Dual-track fixture demonstration
├── pyproject.toml
└── LICENSE
```

## Requirements

- **Python** ≥ 3.9
- **No runtime dependencies** — standard library only
- `opencode` CLI is optional and only needed for the live CLI execution provider
  (not required for fixture-local or deterministic modes)

## License

MIT — see [LICENSE](LICENSE).
