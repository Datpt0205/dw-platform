"""Entitlement service: plan-level capability checks (implements ``EntitlementPort``)."""

from __future__ import annotations

from dataclasses import dataclass

from dw_kernel.errors import EntitlementDeniedError
from dw_platform.application.access_context import AccessContext


@dataclass(frozen=True)
class PlanEntitlementService:
    """Features from the access context.

    A plan's features reach the `AccessContext` from `platform.plans.features`
    joined with the tenant's overrides when the context is built, so that is
    the one place a feature is read. A plan's numbers are not answered here:
    `platform.plan_limits` is read by `dw_usage`'s limits, in the transaction
    that admits a run (usage-and-limits R4.1; ADR-0121 decisions 4, 9).
    """

    def has_feature(self, context: AccessContext, feature: str) -> bool:
        return context.has_feature(feature)

    async def require_feature(self, context: AccessContext, feature: str) -> None:
        if self.has_feature(context, feature):
            return
        raise EntitlementDeniedError(
            "plan does not include this capability",
            details={"feature": feature, "plan_id": context.plan_id},
        )
