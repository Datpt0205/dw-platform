"""A plan catalogue a test fills itself, for `PlanEntitlementService` and the
runner's allowance without a database.

It declares no plan and no number: a test hands it the `PlanLimits` it means
(usage-and-limits ticket 01), so no second copy of `platform.plan_limits`
lives here. Like the adapter, a plan it was not given is `None`, which the
service refuses; `failing` makes every read raise, as a database that cannot
be reached does, and `reads` counts what reached it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dw_platform.application.plan_catalog import PlanLimits


@dataclass
class InMemoryPlanCatalog:
    rows: Mapping[str, PlanLimits] = field(default_factory=dict)
    failing: Exception | None = None
    reads: int = 0

    async def limits(self, plan_id: str) -> PlanLimits | None:
        self.reads += 1
        if self.failing is not None:
            raise self.failing
        return self.rows.get(plan_id)
