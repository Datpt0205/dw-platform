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
- `LimitMetric`: the one table of `metric` names every `limit_exceeded` carries
  (usage-and-limits/04 step 2), the period and lease metrics beside the
  behavioural ones, so a parent step tells a child's spent steps from a spent
  month by name (gate 4/11/2026 of ticket 06 (f)). Here, not in `dw_usage`,
  because the runtime raises the behavioural ones and may not import it;
  `dw_usage.domain.limits.Metric` is the period part, checked against this.
- `LeaseInForce`: the lease a model door that takes no run context (an
  embedding, a rerank) spends against, set by whoever holds that lease for as
  long as it holds it: the runner for a run, `held_operation` for an
  operation outside any run (usage-and-limits R6.1, R6.2). No lease in force,
  no call: such a door refuses rather than send unmetered.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from dw_kernel.errors import InfrastructureError, QuotaExceededError

__all__ = [
    "BEHAVIOUR_METRICS",
    "LEASE_EXPIRED",
    "LIMITS_UNAVAILABLE",
    "LIMIT_EXCEEDED",
    "NO_LEASE",
    "PERIOD_METRICS",
    "LeaseInForce",
    "LimitExceededError",
    "LimitMetric",
    "LimitsUnavailableError",
    "MeterPermit",
    "MeteredCall",
    "lease_in_force",
    "spending_under",
]

LIMIT_EXCEEDED: Final = "limit_exceeded"
LIMITS_UNAVAILABLE: Final = "limits_unavailable"
# `details.reason` of a call on a lease the reaper closed (R5.9).
LEASE_EXPIRED: Final = "lease_expired"

# `details.reason` of a call no lease was in force for (usage-and-limits R6.2).
NO_LEASE: Final = "no_lease"

# The metric names of every `limit_exceeded` (usage-and-limits/04 step 2): the
# period and lease metrics, then the behavioural limits of one run.
LimitMetric = Literal["cost_usd", "tokens", "runs", "steps", "model_calls", "tool_calls"]
PERIOD_METRICS: Final[tuple[LimitMetric, ...]] = ("cost_usd", "tokens", "runs")
BEHAVIOUR_METRICS: Final[tuple[LimitMetric, ...]] = ("steps", "model_calls", "tool_calls")


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


@dataclass(frozen=True, slots=True)
class LeaseInForce:
    """Who holds the lease a door without a run context spends against.

    `lease_root` is the lease's key, a run tree's root or an operation's id;
    `run_id` the run a call belongs to, `None` for an operation outside any
    run; `purpose` the lease's (`run`, `ingestion`, `retrieval`,
    `builder_assist`); `actor_id` and `actor_kind` whom the usage record
    names; `cost_ceiling_usd` a gate attempt's own ceiling inside its lease."""

    tenant_id: UUID
    workspace_id: UUID
    lease_root: UUID
    run_id: UUID | None
    purpose: str
    actor_id: UUID | None
    actor_kind: Literal["user", "service", "system"]
    cost_ceiling_usd: Decimal | None = None


# A ContextVar, like the usage meter's claim tally: it belongs to one run or
# one operation, propagates into the tasks it spawns, and cannot leak between
# two of them on one event loop.
_IN_FORCE: ContextVar[LeaseInForce | None] = ContextVar("dw_lease_in_force", default=None)


def lease_in_force() -> LeaseInForce | None:
    """The lease the current run or operation holds, or `None`."""
    return _IN_FORCE.get()


@contextmanager
def spending_under(holder: LeaseInForce) -> Iterator[None]:
    """Make `holder` the lease in force for the block, and put back the one
    before it on the way out, however the block ends."""
    token = _IN_FORCE.set(holder)
    try:
        yield
    finally:
        _IN_FORCE.reset(token)


@dataclass(frozen=True)
class MeteredCall:
    """One embedding or rerank call, as the meter is asked about it before it
    is sent (usage-and-limits R6.1): what it is, the price key of its route,
    what it sends, priced by `units` (`embedding_input` tokens, one
    `rerank_search_unit`), and where it is processed, for its usage record."""

    operation: Literal["embeddings", "rerank"]
    provider: str
    model: str
    input_tokens: int
    units: Mapping[str, int]
    data_location: str | None
    processor: str | None


@dataclass(frozen=True)
class MeterPermit:
    """A call the lease in force let through: its usage record's key."""

    lease_id: UUID
    call_id: UUID
    occurred_at: datetime
