"""Entitlement service: plan-level capability checks (implements ``EntitlementPort``)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dw_kernel.errors import EntitlementDeniedError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.plan_catalog import PlanCatalogPort


@dataclass(frozen=True)
class PlanEntitlementService:
    """Features from the access context; limits from the plan catalogue.

    A plan's features reach the `AccessContext` from `platform.plans.features`
    joined with the tenant's overrides when the context is built, so that is
    the one place a feature is read. Its numbers come from `platform.plan_limits`
    through ``catalog`` (usage-and-limits R1.1).
    """

    catalog: PlanCatalogPort

    def has_feature(self, context: AccessContext, feature: str) -> bool:
        return context.has_feature(feature)

    async def runs_per_day(self, plan_id: str) -> int | None:
        """Satisfies ``dw_agent_runtime.ports.RunAllowancePort``.

        A plan with no `platform.plan_limits` row is refused outright (0),
        never treated as unlimited (R1.2): an operator seeing runs refused for
        a plan they just created is the failure that gets fixed; unlimited
        runs on an unpriced plan is the one nobody notices until the invoice.
        A catalogue that cannot be read raises, and the run is not admitted.
        """
        limits = await self.catalog.limits(plan_id)
        if limits is None:
            return 0
        return limits.runs_per_day

    async def spend_usd_per_day(self, plan_id: str) -> Decimal | None:
        """Satisfies `dw_agent_runtime.ports.RunAllowancePort.spend_usd_per_day`.

        The plan's `cost_usd_per_day`, with the same refusal as `runs_per_day`
        for a plan with no row: spend nothing more today.
        """
        limits = await self.catalog.limits(plan_id)
        if limits is None:
            return Decimal(0)
        return limits.cost_usd_per_day

    async def require_feature(self, context: AccessContext, feature: str) -> None:
        if self.has_feature(context, feature):
            return
        raise EntitlementDeniedError(
            "plan does not include this capability",
            details={"feature": feature, "plan_id": context.plan_id},
        )
