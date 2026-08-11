# Issue Fusion

Cluster duplicate reports into an `IssueCluster`. Preserve source identifiers,
timestamps, symptom text, and an evidence digest. Do not modify a repository or
infer a root cause.

In a native run, read `codeops-state.task_get`, publish `IssueCluster` with
`codeops-state.artifact_put` at the returned `state_version`, then call
`codeops-state.state_transition` to `FUSED` using that same expected version.
Your AgentTeams gateway identity must be the artifact producer and state owner.
