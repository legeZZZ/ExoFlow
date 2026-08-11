---
name: safe-patch-exec
version: 0.1.0
artifact: PatchBundle
---
# Safe Patch Execution

Require a scope-bound Human approval with matching task and state version.
Apply the smallest change in an isolated workspace, reject any path escape,
and return only PatchBundle metadata. Testing belongs to VerifyAndReplay and
the independent CIPort, never to this executor.
