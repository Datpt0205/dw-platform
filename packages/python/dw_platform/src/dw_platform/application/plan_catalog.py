"""What a plan grants, as numbers: the one question every limit reader asks.

`platform.plan_limits` is the single owner of these numbers (usage-and-limits
R1.1, ADR-0121 decision 9). Before it, the same three plans lived twice — in
`platform.plans.quotas` and in a dict in `entitlement.py` that the runtime
actually read — and nothing made the two disagree loudly (failure-modes #2).
So nothing outside the adapter that reads the table builds a `PlanLimits`;
`tests/unit/test_plan_catalogue_owner.py` scans the source for it.

The constraints (non-negative, per-run maxima NOT NULL, steps in 1..500) are
the database's, by CHECK; a value object here would be a second copy of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PlanLimits:
    """One row of `platform.plan_limits`. ``None`` means no limit, never zero.

    Read in W1: `runs_per_day` and `cost_usd_per_day`, by the runner's daily
    allowance. The monthly ceilings and the per-run maxima have their readers
    in usage-and-limits tickets 03, 04 and 06; until ticket 03, a model
    profile's `ModelBudgets` still caps a run (ticket 01, Comments M3).
    """

    plan_id: str
    runs_per_day: int | None
    cost_usd_per_day: Decimal | None
    cost_usd_per_month: Decimal | None
    tokens_per_month: int | None
    max_cost_usd_per_run: Decimal
    max_tokens_per_run: int
    max_steps_per_run: int
    max_model_calls_per_run: int
    max_tool_calls_per_run: int


class PlanCatalogPort(Protocol):
    """The plan catalogue, read-only (R1.1).

    ``None`` is "this plan has no row", which the caller refuses on (R1.2);
    it never stands for "unlimited". A catalogue that cannot be read raises:
    it never answers from a stale copy or with a guess (failure-modes #7).
    """

    async def limits(self, plan_id: str) -> PlanLimits | None: ...
