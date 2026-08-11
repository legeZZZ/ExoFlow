# Environment Bootstrap

Create an isolated task workspace, record the repository revision and public
baseline, and publish an `EnvironmentSnapshot`. Hidden verifier material must
remain outside the executor workspace.

Publish `EnvironmentSnapshot` through `codeops-state.artifact_put`, including
workspace and revision evidence references, then compare-and-swap the task to
`BOOTSTRAPPED`. Never put hidden-test paths or content in this artifact.
