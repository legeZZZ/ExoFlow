# ExoFlow

**Multi-agent software engineering orchestration with a deterministic state machine core.**

ExoFlow coordinates specialist AI agents through a typed, CAS-guarded state machine to
triage issues, locate root causes, execute verified patches, and distill operational
knowledge — all without leaving an auditable event chain.

## Why ExoFlow?

- **Deterministic control plane** — a single state machine definition (`state_machine_def.py`)
  is the only source of truth; every transition is CAS-guarded and actor-attributed.
- **Pure Python stdlib** — zero runtime dependencies. Python ≥ 3.9, installable offline.
- **Typed artifacts** — every agent output is schema-validated and stored with version,
  digest, and provenance.
- **Auditable event chain** — SQLite-backed event store records every state transition,
  gate check, and artifact write.
- **Skill distillation** — successful agent trajectories are distilled into reusable
  skill packages with eval regression guards.

## Architecture

```
                  ┌──────────────────────┐
                  │   Native MCP Server   │  ← 12 tools, CAS, guardrails
                  │   (native_mcp.py)     │
                  └──────────┬───────────┘
                             │ typed events + artifacts
                  ┌──────────▼───────────┐
                  │   State Machine       │  ← single source of truth
                  │   (state_machine_def) │
                  └──────────┬───────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
   ┌────▼─────┐  ┌─────▼──────┐  ┌──────▼──────┐
   │  Intake   │  │  Triage    │  │  Verifier   │  ...
   │  Worker   │  │  Worker    │  │  Worker     │
   └──────────┘  └────────────┘  └─────────────┘
```

## Quick Start

```bash
cd /path/to/exoflow

# Install (no dependencies)
python3 -m pip install . --no-deps --no-build-isolation

# Run both track fixtures
PYTHONPATH=src python3 run_demo.py

# Run all tests
PYTHONPATH=src python3 -m unittest discover -s tests -v

# CLI entry point
python3 -m goai_control_tower --track track1 --track1-input src/goai_control_tower/samples/track1/input.json
```

## Tracks

### Track 1 — CodeOps Control Tower

End-to-end code fix pipeline: intake → triage → env bootstrap → repo analysis →
plan → approval → patch → verify → release → postmortem → skill distillation.

- 9 specialist worker agents with typed SKILL manifests
- Hidden test verification with independent verifier workspace
- `fixture-local` provider for deterministic replay

### Track 2 — Causal Growth Attribution

Insurance growth attribution with causal gates:
- **Case A**: observational (descriptive only, no causal claims)
- **Case B**: missing experiment metadata (fails closed)
- **Case C**: randomized assignment (ITT estimate with 95% CI)
- Process-isolated oracle benchmark for reproducibility

## Package Structure

```text
ExoFlow/
├── src/goai_control_tower/    ← core library (pure Python stdlib)
│   ├── state_machine_def.py   ← state machine definition
│   ├── native_mcp.py          ← MCP state authority server
│   ├── skill_distill.py       ← trajectory distillation
│   └── track1.py / track2.py  ← track implementations
├── packages/                  ← worker SKILL manifests
│   ├── team-leader/           ← orchestration agent
│   ├── skills/                ← 11 specialist skills with evals
│   └── ...
└── tests/                     ← unit tests
```

## Requirements

- Python ≥ 3.9
- No runtime dependencies (stdlib only)
- `opencode` CLI is optional (only for live CLI execution path)

## License

MIT — see [LICENSE](LICENSE).
