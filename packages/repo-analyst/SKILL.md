# Repository Analysis

Perform read-only repository mapping and root-cause analysis. Produce at least
two falsifiable `RootCauseHypotheses` with supporting and opposing evidence.
This skill must not emit an executable patch.

After reading the authoritative version, publish `RootCauseHypotheses` through
`codeops-state.artifact_put` and compare-and-swap to `LOCATED`. The state MCP
will reject this Worker identity if it attempts to publish `PatchBundle`.
