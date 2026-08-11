# Bounded Change Planning

Produce ranked `ChangePlan` candidates with approved file scope, commands,
rollback, risk, expected verification, and a plan digest. Planning never
authorizes execution.

Publish `ChangePlan`, transition to `PLANNED`, then call
`codeops-state.approval_request` with the exact file/command scope, expected
state `AWAITING_APPROVAL`, and current version. Transition to
`AWAITING_APPROVAL` only with compare-and-swap. Send the returned approval ID
and scope digest to the Team Room; do not interpret the request as approval.
