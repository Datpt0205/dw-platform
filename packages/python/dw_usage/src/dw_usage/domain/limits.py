"""Limits on the scope chain, in W1 (usage-and-limits R4, R5; ADR-0121
decisions 4, 5, 9).

- The four (`metric`, `window_kind`) pairs a policy may name, each with the one
  column of `platform.plan_limits` that caps it (R4.14); the database holds the
  same four in a CHECK (R4.16), and `test_limits_catalog.py` reads them back.
- The scope ranks that order every lock on the counters (tenant, workspace,
  then agent or workflow), so two admissions never wait on each other in a
  circle (ADR-0121 decision 5).
- The merge of the plan's caps and a company's policies into the limits of one
  run's chain: at the company, one counter serves both and the smaller number
  is the limit, named `plan` or `policy` (gate 4/11/2026 (p)).
- What a lease holds of a counter: `reserved - rolled`, never below zero.

W1 has no workspace tree (org-and-principals: the tree is W2), so a
workspace's ancestors in the chain are its company alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, get_args
from uuid import UUID

from dw_usage.domain.windows import WindowKind

__all__ = [
    "LEASE_PURPOSES",
    "LIMIT_PAIRS",
    "PLAN_COLUMNS",
    "SCOPE_TYPES",
    "CounterKey",
    "LeasePurpose",
    "LimitKind",
    "LimitSource",
    "Metric",
    "PlanCaps",
    "PolicyLimit",
    "ScopeLimit",
    "ScopeType",
    "chain_limits",
    "held",
    "remaining",
    "scope_rank",
]

ScopeType = Literal["tenant", "workspace", "agent", "workflow"]
SCOPE_TYPES: Final[tuple[ScopeType, ...]] = get_args(ScopeType)
Metric = Literal["cost_usd", "tokens", "runs"]
LimitKind = Literal["hard"]
LimitSource = Literal["plan", "policy"]
LeasePurpose = Literal["run", "eval_offline", "ingestion", "retrieval", "builder_assist"]
LEASE_PURPOSES: Final[tuple[LeasePurpose, ...]] = get_args(LeasePurpose)

# The W1 pairs, each with the plan column that caps it (R4.14).
PLAN_COLUMNS: Final[dict[tuple[Metric, WindowKind], str]] = {
    ("cost_usd", "day"): "cost_usd_per_day",
    ("cost_usd", "month"): "cost_usd_per_month",
    ("tokens", "month"): "tokens_per_month",
    ("runs", "day"): "runs_per_day",
}
LIMIT_PAIRS: Final[tuple[tuple[Metric, WindowKind], ...]] = tuple(PLAN_COLUMNS)

# The order every lock on `platform.budget_counters` is taken in.
_RANK: Final[dict[str, int]] = {"tenant": 0, "workspace": 1, "agent": 2, "workflow": 2}


def scope_rank(scope_type: str) -> int:
    return _RANK[scope_type]


@dataclass(frozen=True, slots=True)
class PlanCaps:
    """The plan's numbers a run is held to: its period caps by pair (`None`
    is no limit) and its per-run ceilings, NOT NULL (ADR-0121 decision 9)."""

    plan_id: str
    periods: dict[tuple[Metric, WindowKind], Decimal | None]
    max_cost_usd_per_run: Decimal
    max_tokens_per_run: int


@dataclass(frozen=True, slots=True)
class PolicyLimit:
    """One `platform.limit_policies` row of the chain."""

    scope_type: ScopeType
    scope_id: UUID
    metric: Metric
    window_kind: WindowKind
    limit_value: Decimal


@dataclass(frozen=True, slots=True)
class ScopeLimit:
    """One limit of the chain: the scope it holds, the pair, the number."""

    scope_type: ScopeType
    scope_id: UUID
    metric: Metric
    window_kind: WindowKind
    limit: Decimal
    source: LimitSource

    @property
    def order(self) -> tuple[int, str, str, str]:
        return (scope_rank(self.scope_type), str(self.scope_id), self.metric, self.window_kind)


@dataclass(frozen=True, slots=True)
class CounterKey:
    """A row of `platform.budget_counters`: a limit's scope and pair in one window."""

    scope_type: ScopeType
    scope_id: UUID
    metric: Metric
    window_kind: WindowKind
    window_start: datetime
    window_end: datetime

    @property
    def order(self) -> tuple[int, str, str, str, str]:
        return (
            scope_rank(self.scope_type),
            str(self.scope_id),
            self.metric,
            self.window_kind,
            self.window_start.isoformat(),
        )


def chain_limits(
    tenant_id: UUID,
    plan: PlanCaps | None,
    policies: list[PolicyLimit],
) -> list[ScopeLimit]:
    """The limits of one chain, in lock order. The plan's caps hold at the
    company; a company policy of the same pair shares that scope's counter and
    the smaller number wins. `plan` is `None` for a lease no company cap
    reaches (a gate the platform pays for, DO-29.2 (a))."""
    found: dict[tuple[str, UUID, str, str], ScopeLimit] = {}
    if plan is not None:
        for (metric, window_kind), value in plan.periods.items():
            if value is not None:
                found[("tenant", tenant_id, metric, window_kind)] = ScopeLimit(
                    "tenant", tenant_id, metric, window_kind, value, "plan"
                )
    for policy in policies:
        key = (policy.scope_type, policy.scope_id, policy.metric, policy.window_kind)
        current = found.get(key)
        if current is None or policy.limit_value < current.limit:
            found[key] = ScopeLimit(
                policy.scope_type,
                policy.scope_id,
                policy.metric,
                policy.window_kind,
                policy.limit_value,
                "policy",
            )
    return sorted(found.values(), key=lambda limit: limit.order)


def remaining(limit: Decimal, used: Decimal, reserved: Decimal) -> Decimal:
    """What a counter has left: `limit - used - reserved` (R5.8)."""
    return limit - used - reserved


def held(reserved: Decimal, rolled: Decimal) -> Decimal:
    """What a lease still holds of each of its counters' `reserved`."""
    return max(reserved - rolled, Decimal(0))
