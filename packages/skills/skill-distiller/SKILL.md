---
name: skill-distiller
version: 0.1.0
artifact: SkillCandidate
---
# Skill Distiller

Distill a reusable SkillCandidate only from complete, provenance-linked traces.
The candidate must contain trigger, steps, boundaries, counterexamples,
source traces, and four promotion tests: fidelity, generalization,
counterexample, and secret/license scan. Proposing is never publishing;
promotion requires Human approval and canary rollback.
