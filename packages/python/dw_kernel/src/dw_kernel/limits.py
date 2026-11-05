"""The refusals of a hard limit (usage-and-limits R4.10, R5.2, R5.5, R5.9, R5.10;
ADR-0121 decisions 5, 6).

Here rather than in `dw_usage`, which answers `LimitsPort`, because the runtime
that meets them must tell them apart without importing the package that raises
them, the way `dw_kernel.residency` holds the residency refusal.

- `LimitExceededError`: a period, a per-run ceiling or a lease has nothing left
  for what is asked. A `QuotaExceededError`, so the old inline path still
  answers 429 (ADR-0121 decision 6); a Studio run never reaches HTTP with it.
  `details` always carries `reason_code` `limit_exceeded` and the `metric`.
- `LimitsUnavailableError`: the policies or the counters could not be read, so
  no run is admitted on a guess (failure-modes #7); `limits_unavailable`, which
  the refusal table of workflow-engine treats as `control_state_unavailable`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, Literal

from dw_kernel.errors import InfrastructureError, QuotaExceededError

__all__ = [
    "LEASE_EXPIRED",
    "LIMITS_UNAVAILABLE",
    "LIMIT_EXCEEDED",
    "LimitExceededError",
    "LimitMetric",
    "LimitsUnavailableError",
]

LIMIT_EXCEEDED: Final = "limit_exceeded"
LIMITS_UNAVAILABLE: Final = "limits_unavailable"
# `details.reason` of a call on a lease the reaper closed (R5.9).
LEASE_EXPIRED: Final = "lease_expired"

# The metric names of every `limit_exceeded` (usage-and-limits/04 step 2 adds
# the behavioural ones beside them).
LimitMetric = Literal["cost_usd", "tokens", "runs"]


class LimitExceededError(QuotaExceededError):
    """Nothing is left of a limit for what was asked; nothing was spent."""

    def __init__(
        self,
        message: str,
        *,
        metric: LimitMetric,
        scope_type: str,
        window: str | None = None,
        limit: Decimal | int | None = None,
        used: Decimal | int | None = None,
        resets_at: datetime | None = None,
        limit_source: str | None = None,
        reason: str | None = None,
    ) -> None:
        details: dict[str, object] = {
            "reason_code": LIMIT_EXCEEDED,
            "metric": metric,
            "scope_type": scope_type,
        }
        optional: dict[str, object | None] = {
            "window": window,
            "limit": None if limit is None else str(limit),
            "used": None if used is None else str(used),
            "resets_at": None if resets_at is None else resets_at.isoformat(),
            "limit_source": limit_source,
            "reason": reason,
        }
        details.update({key: value for key, value in optional.items() if value is not None})
        super().__init__(message, details=details)


class LimitsUnavailableError(InfrastructureError):
    """The limits could not be read: refuse, never admit unbounded."""

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message, details={"reason_code": LIMITS_UNAVAILABLE, **(details or {})})
