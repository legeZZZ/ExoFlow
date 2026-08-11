# Approved Patch Execution

Apply only the approved file scope in the task workspace. Return a
`PatchBundle` containing the diff digest, changed files, workspace reference,
and side effects. Do not run or report verification results; the independent
CIPort owns those results.

Before execution, call `codeops-state.approval_status` and require `APPROVED`,
the expected state/version, and Matrix decision evidence. Publish
`PatchBundle` with its `approval_id`, non-empty `changed_files`, diff digest and
workspace evidence. Only then compare-and-swap to `PATCHED`; the MCP authority
rejects missing approval bindings and files outside the approved scope.
