"""Small retry primitive used by the Track 1 execution fixture."""

from __future__ import annotations

import time
from typing import Callable, Optional, TypeVar


T = TypeVar("T")


class DuplicateSideEffectError(RuntimeError):
    """Raised when an ambiguous timeout could duplicate an external effect."""


def execute_with_retry(
    operation: Callable[[float, Optional[str]], T],
    timeout_budget: float,
    attempts: int = 2,
    idempotency_key: Optional[str] = None,
) -> T:
    """Execute an operation with a total timeout budget."""

    if timeout_budget <= 0 or attempts < 1:
        raise ValueError("timeout_budget and attempts must be positive")

    for _ in range(attempts):
        try:
            return operation(timeout_budget, idempotency_key)
        except TimeoutError:
            continue
    raise TimeoutError("operation timed out")
