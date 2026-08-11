# Risk Triage

Produce a `RiskAssessment` with blast radius, affected scope, action level,
approval requirement, and uncertainty. A missing risk fact must result in a
human escalation rather than an optimistic default.

In a native run, read `codeops-state.task_get`, publish `RiskAssessment` with
`codeops-state.artifact_put`, then compare-and-swap the same version to
`TRIAGED`. A stale-version response requires rereading state, not retrying the
old write.
