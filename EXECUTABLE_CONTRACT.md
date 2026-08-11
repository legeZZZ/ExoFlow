# GOAI Executable Contract v0.1

This file is the implementation contract for the first vertical slices. It is
intentionally shorter than the competition plans. A claim is considered
implemented only when its event, artifact, evidence and test are present.

## Runtime Boundary

- `AgentTeamsControlPlane` is the local conformance runtime and the only task
  state writer.
- A hosted AgentTeams adapter will own platform resources behind the domain
  workflow: Manager/Team/Worker identity, Matrix rooms, shared artifacts,
  skill dispatch and platform lifecycle. The local runtime remains a
  conformance harness until that adapter is exercised against a pinned
  AgentTeams installation.
- `SQLiteCheckpointProvider` stores recovery snapshots only. It cannot issue a
  transition or become a second state authority.
- Evidence and trace use the same `task_id` and `trace_id`.

## Track 1 First Slice

The fixture `T1-codeops-demo` must pass:

```text
RECEIVED -> FUSED -> TRIAGED -> BOOTSTRAPPED -> LOCATED -> PLANNED
-> AWAITING_APPROVAL -> PATCHED -> VERIFYING
-> PATCHED -> VERIFYING -> RELEASE_READY -> POSTMORTEM
-> SKILL_DISTILLING -> CLOSED
```

The first verification attempt fails with a structured
`REGRESSION_TIMEOUT_GUARD` signature. The second attempt passes hidden
verification. The approval scope, provider result, failure signature and
postmortem SkillCandidate must be linked from the Evidence Pack.

All 8 Agent identities, 12 Skill manifests and 15 Port manifests are
registered. The `fixture-local` Provider is the first real execution slice: it
copies a fixture into an isolated workspace and applies only the approved file
scope. An independent `CIPort` runs public tests in the Agent workspace and
hidden tests in a separate verifier workspace. The Executor Provider never
supplies a verification verdict. The `opencode` Provider remains available in
deterministic dry-run mode; live CLI execution is opt-in through
`GOAI_OPENCODE_LIVE=1` and is never required by tests.

## Track 2 First Slice

InsurSim produces bounded user-level rates and separates generation, workflow
and evaluation truth. The first implementation uses:

- bounded logistic links for funnel probabilities;
- randomized assignment only in Case C;
- observational confounding in Case A;
- missing experiment metadata in Case B;
- ITT difference in means for Case C;
- a fixed-order log-chain decomposition for structural contribution;
- Claim Ledger output that prevents causal verbs when readiness fails.

Case acceptance:

| Case | Expected outcome | Public behavior |
|---|---|---|
| A | `DESCRIPTIVE_ONLY` | Show co-movement, decomposition and pre-experiment draft |
| B | `DATA_INSUFFICIENT` | Fail closed, show missing fields and补数 path |
| C | `CAUSAL_READY` | Show ITT estimate, 95% CI, guardrails and monitoring |

## Evidence Minimum

Every vertical slice must expose:

1. state transition events with actor and reason;
2. typed artifacts with schema version and evidence references;
3. evidence content digests;
4. approval decisions and scope;
5. final state and failure or refusal reason;
6. a reproducible fixture and seed.
