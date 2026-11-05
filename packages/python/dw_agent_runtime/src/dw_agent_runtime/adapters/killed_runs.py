"""`SqlKilledRuns`: what the `control_switch` lane reads and writes, as
`dw_app` under one company's RLS (agent-lifecycle R8.2, R8.10).

`platform.control_switches`, `platform.worker_runs` and
`platform.approval_requests` are narrowed by tenant alone, so the lane needs
no tenant-wide scope (`tenant_wide_scope()`): it reads one company's rows of
one component. The parked runs are found through
`ix_worker_runs_tenant_id_artifact_id_created_at`, their pending requests
through `ix_approval_requests_tenant_id_run_id_pending` (b735015cca5c).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_agent_runtime.control_switch_lane import (
    PARKED_STATUSES,
    OpenKillOfRuns,
    ParkedRun,
)
from dw_agent_runtime.run_control import HaltReason
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.repositories import (
    SqlApprovalRepository,
    SqlAuditRepository,
    _approval_from_row,
)
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.domain.approval import ApprovalRequest, ApprovalStatus
from dw_platform.domain.audit import AuditEvent

__all__ = ["SqlKilledRuns"]

_SWITCHES = sa.table(
    "control_switches",
    sa.column("id", sa.Uuid),
    sa.column("action"),
    sa.column("target_id", sa.Uuid),
    sa.column("set_by", sa.Uuid),
    sa.column("lifted_at", sa.DateTime(timezone=True)),
    schema="platform",
)
_OPEN_KILL = sa.and_(_SWITCHES.c.action == "kill", _SWITCHES.c.lifted_at.is_(None))
_PARKED = sa.and_(
    worker_runs.c.status.in_(sorted(PARKED_STATUSES)),
    worker_runs.c.run_mode != "simulate",
)


@dataclass
class _CancelTx:
    """`KillCancelTx` over one session bound to one company."""

    session: AsyncSession

    async def kill_open(self, switch_id: uuid.UUID) -> bool:
        found = await self.session.scalar(
            sa.select(_SWITCHES.c.id)
            .where(_SWITCHES.c.id == switch_id, _OPEN_KILL)
            .with_for_update(read=True)
        )
        return found is not None

    async def parked(self, run_id: uuid.UUID) -> ParkedRun | None:
        row = (
            await self.session.execute(
                sa.select(worker_runs.c.id, worker_runs.c.workspace_id)
                .where(worker_runs.c.id == run_id, _PARKED)
                .with_for_update()
            )
        ).first()
        return None if row is None else ParkedRun(run_id=row.id, workspace_id=row.workspace_id)

    async def pending_approvals(self, run_id: uuid.UUID) -> list[ApprovalRequest]:
        approvals = tables.approval_requests
        rows = await self.session.execute(
            sa.select(approvals)
            .where(
                approvals.c.run_id == run_id,
                approvals.c.status == ApprovalStatus.PENDING.value,
            )
            .order_by(approvals.c.id)
            .with_for_update()
        )
        return [_approval_from_row(row) for row in rows]

    async def save_approval(self, request: ApprovalRequest) -> None:
        await SqlApprovalRepository(self.session).save(request)

    async def cancel(self, run_id: uuid.UUID, *, switch_id: uuid.UUID) -> None:
        await self.session.execute(
            sa.update(worker_runs)
            .where(worker_runs.c.id == run_id)
            .values(
                status=RunStatus.CANCELLED.value,
                error={"code": HaltReason.ARTIFACT_KILLED.value, "switch_id": str(switch_id)},
                updated_at=sa.func.now(),
            )
        )

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)


@dataclass(frozen=True)
class SqlKilledRuns:
    """Implements `KilledRunsPort` as `dw_app`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def open_kill(self, tenant_id: uuid.UUID, switch_id: uuid.UUID) -> OpenKillOfRuns | None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            row = (
                await session.execute(
                    sa.select(_SWITCHES.c.id, _SWITCHES.c.target_id, _SWITCHES.c.set_by).where(
                        _SWITCHES.c.id == switch_id, _OPEN_KILL
                    )
                )
            ).first()
        if row is None or row.target_id is None:
            return None
        return OpenKillOfRuns(switch_id=row.id, target_id=row.target_id, set_by=row.set_by)

    async def parked_runs(self, tenant_id: uuid.UUID, target_id: uuid.UUID) -> list[uuid.UUID]:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            rows = await session.execute(
                sa.select(worker_runs.c.id)
                .where(worker_runs.c.artifact_id == target_id, _PARKED)
                .order_by(worker_runs.c.created_at, worker_runs.c.id)
            )
            return [row.id for row in rows]

    @asynccontextmanager
    async def transaction(self, tenant_id: uuid.UUID) -> AsyncIterator[_CancelTx]:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            yield _CancelTx(session)
