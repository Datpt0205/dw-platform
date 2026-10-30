"""SQL for a Digital Worker's scorecard and its earned levels (digital-worker
R7, R8).

The scorecard is three aggregate statements, one per source, under the
caller's tenant and workspace. The levels change in the transactions the
rules need: a lowering writes only while the class is still at the level the
caller saw; a raise opens its approval where the partial unique index
`uq_approval_requests_dw_autonomy_raise_pending` refuses a second pending one;
a settlement reads the decided approval, the DW's state `FOR SHARE` (retiring
takes the row `FOR UPDATE`) and the class `FOR UPDATE` (a lowering waits on
it), and writes what the application decides in that same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.autonomy import AutonomyLevel
from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlApprovalRepository, SqlAuditRepository
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.decision_gate import DW_DECISION
from dw_platform.application.dw_autonomy import DW_AUTONOMY_RAISE, RaiseFacts, RaiseSettlement
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.scorecard import ScorecardCounts
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent

_CLASSES = tables.dw_decision_classes
_RAISE_PENDING = "uq_approval_requests_dw_autonomy_raise_pending"

# The run table belongs to the agent runtime; the platform reads three columns.
_RUNS = sa.table(
    "worker_runs",
    sa.column("workspace_id"),
    sa.column("run_as_principal_id"),
    sa.column("model_cost_usd"),
    sa.column("created_at"),
    schema="platform",
)


def _scope(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)


@dataclass(frozen=True)
class SqlScorecardRepository:
    """Implements ``ScorecardRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def counts(
        self,
        context: AccessContext,
        *,
        dw_id: uuid.UUID,
        principal_id: uuid.UUID,
        since: datetime,
    ) -> ScorecardCounts:
        w = tables.work_items
        r, d = tables.approval_requests, tables.approval_decisions
        approved = d.c.outcome == "approved"
        async with tenant_session(self.session_factory, _scope(context)) as session:
            items = (
                await session.execute(
                    sa.select(
                        w.c.status,
                        sa.func.count().label("n"),
                        sa.func.count()
                        .filter(sa.and_(w.c.status == "done", w.c.handoff.is_(None)))
                        .label("alone"),
                        sa.func.count().filter(w.c.handoff.is_not(None)).label("handed"),
                    )
                    .where(
                        w.c.dw_id == dw_id,
                        w.c.workspace_id == context.workspace_id,
                        w.c.created_at >= since,
                    )
                    .group_by(w.c.status)
                )
            ).all()
            decisions = (
                await session.execute(
                    sa.select(
                        sa.func.count().filter(sa.and_(approved, sa.not_(d.c.edited))),
                        sa.func.count().filter(sa.and_(approved, d.c.edited)),
                        sa.func.count().filter(d.c.outcome == "rejected"),
                    )
                    .select_from(r.join(d, d.c.request_id == r.c.id))
                    .where(
                        r.c.approval_type == DW_DECISION,
                        # RLS narrows approvals by tenant only.
                        r.c.workspace_id == context.workspace_id,
                        r.c.payload["dw_id"].astext == str(dw_id),
                        r.c.decided_at >= since,
                    )
                )
            ).one()
            cost = (
                await session.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(_RUNS.c.model_cost_usd), 0)).where(
                        _RUNS.c.run_as_principal_id == principal_id,
                        _RUNS.c.workspace_id == context.workspace_id,
                        _RUNS.c.created_at >= since,
                    )
                )
            ).scalar_one()
        return ScorecardCounts(
            items_by_status={row.status: int(row.n) for row in items},
            done_alone=sum(int(row.alone) for row in items),
            handed_off=sum(int(row.handed) for row in items),
            approved_as_is=int(decisions[0]),
            approved_edited=int(decisions[1]),
            rejected=int(decisions[2]),
            model_cost_usd=Decimal(cost),
        )


@dataclass(frozen=True)
class SqlDwAutonomyRepository:
    """Implements ``AutonomyRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def lower(
        self,
        context: AccessContext,
        dw_id: uuid.UUID,
        key: str,
        *,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> bool:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(f"{dw_id}/{key}"))
            moved = (
                await session.execute(
                    sa.update(_CLASSES)
                    .where(
                        _CLASSES.c.dw_id == dw_id,
                        _CLASSES.c.key == key,
                        _CLASSES.c.earned_level == from_level,
                    )
                    .values(earned_level=to_level)
                    .returning(_CLASSES.c.key)
                )
            ).first()
            if moved is None:
                return False
            await SqlAuditRepository(session).append(audit)
        return True

    async def open_raise(
        self,
        context: AccessContext,
        request: ApprovalRequest,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        try:
            async with tenant_session(self.session_factory, _scope(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(request.id))
                await SqlApprovalRepository(session).add(request)
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            refused = refusal(exc)
            if refused is not None and refused[0] == _RAISE_PENDING:
                raise ConflictError(
                    "a raise of this decision class is already waiting for a decision",
                    details={"reason_code": "raise_pending"},
                ) from exc
            raise

    async def settle_raise(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[RaiseFacts], RaiseSettlement],
    ) -> RaiseSettlement:
        r, d = tables.approval_requests, tables.approval_decisions
        bound = TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
        async with tenant_session(self.session_factory, bound) as session:
            decided = (
                await session.execute(
                    sa.select(r.c.payload, d.c.outcome, d.c.decided_by, d.c.decided_at)
                    .select_from(r.join(d, d.c.request_id == r.c.id))
                    .where(
                        r.c.id == approval_id,
                        r.c.workspace_id == scope.workspace_id,
                        r.c.approval_type == DW_AUTONOMY_RAISE,
                    )
                )
            ).first()
            if decided is None:
                raise NotFoundError(
                    "no decided raise of that id", details={"approval_id": str(approval_id)}
                )
            payload = dict(decided.payload)
            try:
                dw_id = uuid.UUID(str(payload["dw_id"]))
                key, from_level, to_level = (
                    str(payload[name]) for name in ("decision_class", "from_level", "to_level")
                )
            except (KeyError, ValueError) as exc:
                raise NotFoundError(
                    "the raise names no decision class", details={"approval_id": str(approval_id)}
                ) from exc
            state = (
                await session.execute(
                    sa.select(tables.digital_workers.c.state)
                    .where(tables.digital_workers.c.id == dw_id)
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            earned = (
                await session.execute(
                    sa.select(_CLASSES.c.earned_level)
                    .where(_CLASSES.c.dw_id == dw_id, _CLASSES.c.key == key)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if state is None or earned is None:
                raise NotFoundError(
                    "the raise's decision class is gone", details={"approval_id": str(approval_id)}
                )
            settlement = settle(
                RaiseFacts(
                    approval_id=approval_id,
                    dw_id=dw_id,
                    decision_class=key,
                    approved=decided.outcome == "approved",
                    decided_by=decided.decided_by,
                    decided_at=decided.decided_at,
                    from_level=from_level,
                    to_level=to_level,
                    earned_level=earned,
                    dw_state=state,
                )
            )
            if settlement.level is not None:
                # The class row is held `FOR UPDATE` since it was read: the
                # level `settle` judged is the one this replaces.
                await session.execute(
                    sa.update(_CLASSES)
                    .where(_CLASSES.c.dw_id == dw_id, _CLASSES.c.key == key)
                    .values(earned_level=settlement.level)
                )
            if settlement.audit is not None:
                await SqlAuditRepository(session).append(settlement.audit)
        return settlement
