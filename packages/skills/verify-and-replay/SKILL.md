---
name: verify-and-replay
version: 0.1.0
artifact: VerificationReport
---
# Verify and Replay

Replay a PatchBundle in an independent verifier workspace through CIPort.
Record runner identity, commands, digests, public and hidden results, and a
failure signature. If the independent workspace or evidence is unavailable,
return uncertain or escalate; never trust an Executor verdict.
