---
name: resume-guard
version: 0.1.0
artifact: ResumeDecision
---
# Resume Guard

Recover from a durable checkpoint only after validating state version, lease,
idempotency key, and side-effect evidence. Fence stale writers, choose resume,
restart, compensation, or Human escalation, and record a new fencing token.
