# CodeOps AgentTeams packages

Each package is a runtime bundle referenced by the AgentTeams Worker manifest.
The current files are source packages, not published Nacos artifacts. A
release wrapper must package each directory, calculate a digest, and make the
same immutable bytes available to the AgentTeams controller/runtime.

Every skill must produce typed JSON artifacts under
`shared/tasks/<taskId>/artifacts/` and include the current `state_version` in
its write. Skills never grant permissions by prompt alone; runtime access is
defined by the Worker CR and the configured gateway/storage policy.
