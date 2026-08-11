# Postmortem and Skill Distillation

Summarize the complete trace, failed attempts, final verification, and policy
decisions. Propose a versioned `SkillCandidate` only after review. Publishing a
candidate is separate from proposing it and requires human approval.

Read the complete `codeops-state.evidence_pack`, compare-and-swap to
`POSTMORTEM`, publish `Postmortem`, and publish any `SkillCandidate` as a
separate typed artifact. Move through `SKILL_DISTILLING` to `CLOSED`; never
close a task whose Evidence Pack lacks the independent `VerificationReport`.
