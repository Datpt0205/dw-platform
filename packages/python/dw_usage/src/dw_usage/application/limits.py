"""The company's limits as people see and set them (usage-and-limits R4.5,
R4.6, R4.8, R4.9, R4.14, R4.15; ADR-0121 decision 4; D11).

`GET /api/v1/limits` reads every limit of the company with its counter of the
current period (`platform.usage.read`); `PUT` and `DELETE` of one policy by its
path (`platform.limits.manage`). The rules, in the order a request meets them:

1. the caller holds the key, before anything is read (R4.6);
2. the pair is one of the four of W1 and the kind `hard` (R4.14, R4.8), or 422
   `validation_failed` naming the parameter or `/kind`;
3. the scope is the caller's company, or a workspace, agent or workflow of it,
   read under its RLS (another company's is 404, never told apart from one
   that does not exist), of the kind the path names (422
   `scope_kind_mismatch`);
4. in one transaction, on the row locked `FOR UPDATE` (R4.15): an existing
   policy needs `If-Match` (428, 412 when stale); a value above the plan's cap
   is 422 `limit_above_plan` (R4.5); a raise or a removal is 409
   `second_person_required`, since W1 has no two-person path (R4.9, D11); a new
   or lowered limit applies at once, with one audit event `limits.policy.set`
   (`before`, `after`) in the same transaction (R4.8), and a new one's counter
   is born with the period's usage so far (gate 4/11/2026 (o)).

The adapter holds step 4 and its decision: the comparison must see the locked
row, so it cannot be made here on a read that a concurrent write overtakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol, cast
from uuid import UUID

from dw_kernel.errors import DomainError
from dw_kernel.http_conditions import ExpectedVersion
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import AuthorizationPort
from dw_usage.application.reads import USAGE_READ
from dw_usage.domain.limits import PLAN_COLUMNS, SCOPE_TYPES, LimitSource, Metric, ScopeType
from dw_usage.domain.windows import WindowKind

__all__ = [
    "LIMITS_MANAGE",
    "LIMIT_ABOVE_PLAN",
    "SCOPE_KIND_MISMATCH",
    "SECOND_PERSON_REQUIRED",
    "LimitLine",
    "LimitPolicyService",
    "LimitPolicyStorePort",
    "PolicyRef",
    "PolicyWrite",
    "SetPolicy",
]

LIMITS_MANAGE: Final = "platform.limits.manage"
LIMIT_ABOVE_PLAN: Final = "limit_above_plan"
SECOND_PERSON_REQUIRED: Final = "second_person_required"
SCOPE_KIND_MISMATCH: Final = "scope_kind_mismatch"


@dataclass(frozen=True, slots=True)
class PolicyRef:
    """The one policy a path names; the company is the caller's, never the path's."""

    tenant_id: UUID
    scope_type: ScopeType
    scope_id: UUID
    metric: Metric
    window_kind: WindowKind


@dataclass(frozen=True, slots=True)
class SetPolicy:
    ref: PolicyRef
    limit_value: Decimal
    expected: ExpectedVersion | None
    actor_id: UUID
    workspace_id: UUID


@dataclass(frozen=True, slots=True)
class PolicyWrite:
    """The row as the write left it."""

    ref: PolicyRef
    limit_value: Decimal
    version: int


@dataclass(frozen=True, slots=True)
class LimitLine:
    """One limit of the company as the screen shows it: the policy (none for a
    plan cap alone), the plan's cap at the company, the effective limit along
    the chain, and the current period's counter."""

    scope_type: ScopeType
    scope_id: UUID
    metric: Metric
    window_kind: WindowKind
    limit_value: Decimal | None
    version: int | None
    plan_limit: Decimal | None
    effective_limit: Decimal
    limit_source: LimitSource
    used: Decimal
    reserved: Decimal
    resets_at: datetime


class LimitPolicyStorePort(Protocol):
    """Declared here, satisfied by `dw_usage.adapters.limit_policies_sql`."""

    async def lines(self, tenant_id: UUID) -> list[LimitLine]: ...

    async def put(self, command: SetPolicy) -> PolicyWrite:
        """Steps 3 and 4 of the module's rules, in one transaction."""
        ...

    async def delete(
        self, ref: PolicyRef, expected: ExpectedVersion | None, *, workspace_id: UUID
    ) -> None:
        """Steps 3 and 4 for a removal, which W1 always refuses once the row,
        its version and the caller's `If-Match` are checked."""
        ...


def _pair_problem(metric: str, window_kind: str) -> DomainError | None:
    if (metric, window_kind) in PLAN_COLUMNS:
        return None
    parameter = "metric" if metric not in {m for m, _ in PLAN_COLUMNS} else "window_kind"
    return DomainError(
        "Cặp chỉ số và kỳ này không phải hạn mức của bản này",
        details={
            "errors": [
                {
                    "parameter": parameter,
                    "detail": "one of cost_usd/day, cost_usd/month, tokens/month, runs/day",
                }
            ]
        },
    )


@dataclass(frozen=True)
class LimitPolicyService:
    store: LimitPolicyStorePort
    authz: AuthorizationPort

    async def lines(self, context: AccessContext) -> list[LimitLine]:
        await self.authz.require(
            context=context,
            action=USAGE_READ,
            resource_type="limit_policy",
            resource_id=str(context.tenant_id),
        )
        return await self.store.lines(context.tenant_id)

    async def put(
        self,
        context: AccessContext,
        *,
        scope_type: str,
        scope_id: UUID,
        metric: str,
        window_kind: str,
        limit_value: Decimal,
        kind: str,
        expected: ExpectedVersion | None,
    ) -> PolicyWrite:
        ref = await self._ref(context, scope_type, scope_id, metric, window_kind)
        if kind != "hard":
            # `soft` comes in W2 with its threshold reader (R4.8).
            raise DomainError(
                "Bản này chỉ đặt hạn mức cứng",
                details={"errors": [{"pointer": "/kind", "detail": "must be hard"}]},
            )
        if limit_value < 0:
            raise DomainError(
                "Hạn mức không được âm",
                details={"errors": [{"pointer": "/limit_value", "detail": "must be >= 0"}]},
            )
        return await self.store.put(
            SetPolicy(
                ref=ref,
                limit_value=limit_value,
                expected=expected,
                actor_id=context.principal_id,
                workspace_id=context.workspace_id,
            )
        )

    async def delete(
        self,
        context: AccessContext,
        *,
        scope_type: str,
        scope_id: UUID,
        metric: str,
        window_kind: str,
        expected: ExpectedVersion | None,
    ) -> None:
        ref = await self._ref(context, scope_type, scope_id, metric, window_kind)
        await self.store.delete(ref, expected, workspace_id=context.workspace_id)

    async def _ref(
        self,
        context: AccessContext,
        scope_type: str,
        scope_id: UUID,
        metric: str,
        window_kind: str,
    ) -> PolicyRef:
        await self.authz.require(
            context=context,
            action=LIMITS_MANAGE,
            resource_type="limit_policy",
            resource_id=f"{scope_type}:{scope_id}",
        )
        if scope_type not in SCOPE_TYPES:
            raise DomainError(
                "Phạm vi này không đặt được hạn mức ở bản này",
                details={
                    "errors": [
                        {"parameter": "scope_type", "detail": "tenant, workspace, agent, workflow"}
                    ]
                },
            )
        problem = _pair_problem(metric, window_kind)
        if problem is not None:
            raise problem
        return PolicyRef(
            tenant_id=context.tenant_id,
            # Each checked above against the one set that owns it.
            scope_type=scope_type,
            scope_id=scope_id,
            metric=cast(Metric, metric),
            window_kind=cast(WindowKind, window_kind),
        )
