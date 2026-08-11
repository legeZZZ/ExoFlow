# Track 1 execution fixture

This deliberately small repository is used to test the CodeOps execution
contract. The first bounded patch fixes the total timeout budget. The hidden
check still catches duplicate side effects after an ambiguous timeout. The
second bounded patch adds the idempotency guard.
