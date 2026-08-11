# CodeOps Capability Skills

These are the twelve domain capabilities in the CodeOps M:N Skill graph. They
are intentionally separate from the nine role packages in `packages/*`:
Worker identity and runtime belong to AgentTeams; capability versioning belongs
to this package layer.

Every capability has a manifest, input and output schema, deterministic policy
gates, executable evaluation cases, and an AgentTeams `SKILL.md` instruction.
The runtime must preserve `task_id`, `trace_id`, and `state_version` on every
artifact write. A skill may propose an action, but it cannot grant approval or
declare independent verification.
