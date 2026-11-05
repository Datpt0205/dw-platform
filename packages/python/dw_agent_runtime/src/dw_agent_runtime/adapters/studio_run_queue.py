"""`SqlStudioRunQueue`: the queue of Studio runs as `dw_app`, over
`platform.worker_runs` (workflow-engine/04: R5.2-R5.7, R5.23; ADR-0113
decisions 2, 3).

Three reads cross tenants, each through a SECURITY DEFINER function that
returns tenant ids and nothing else (`platform.studio_run_scopes_due`,
`studio_run_orphans_due`, `studio_run_deadlines_due`, revision
`2611a825560d`). Every other statement runs under one tenant's RLS, set per
transaction: the claim (an `UPDATE` over a `MATERIALIZED` pick `FOR UPDATE
SKIP LOCKED`, measured to take exactly `limit` rows behind a 10,000-row
backlog that was never analysed, discovery/14 S-RT (a)), the heartbeat and the
hand-back of one claim, and the reaper's two passes. `platform.worker_runs` is
narrowed by tenant alone, so no lane here needs `tenant_wide_scope()`.

The reaper writes as itself (`lane_audit_event`, actor
`system:studio_run_reaper`), in the transaction that moves the run: a dead
letter's audit and its outbox event `studio.run.dead_lettered` (R5.7), a
deadline's audit `run.deadline_exceeded` (R5.23).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.run_store import RunStatus
from dw_agent_runtime.adapters.runtime_tables import STUDIO_RUN as _STUDIO
from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_agent_runtime.ports import ReapedRuns, StudioClaim
from dw_agent_runtime.studio_lane import REAPER_LANE
from dw_kernel.ids import TenantId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_platform.adapters.persistence.repositories import SqlAuditRepository, SqlOutboxRepository
from dw_platform.domain.audit import lane_audit_event, system_actor
from dw_platform.domain.outbox import OutboxEvent

__all__ = ["DEAD_LETTERED_EVENT", "SqlStudioRunQueue"]

DEAD_LETTERED_EVENT: Final = "studio.run.dead_lettered"
_DEAD_LETTERED: Final = "run.dead_lettered"
_DEADLINE_EXCEEDED: Final = "run.deadline_exceeded"
_UNFINISHED: Final = ("queued", "running", "waiting", "blocked")

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SCOPES_DUE = sa.text("SELECT tenant_id FROM platform.studio_run_scopes_due(:limit)")
_ORPHANS_DUE = sa.text("SELECT tenant_id FROM platform.studio_run_orphans_due(:limit)")
_DEADLINES_DUE = sa.text(
    "SELECT tenant_id FROM platform.studio_run_deadlines_due(:limit, :unclaimed_after)"
)
# The claim, under the tenant's RLS (R5.3): never inside a definer function.
_CLAIM = sa.text(
    """
    WITH picked AS MATERIALIZED (
        SELECT id FROM platform.worker_runs
        WHERE status = 'queued' AND artifact_kind IS NOT NULL AND available_at <= now()
        ORDER BY priority, available_at, created_at, id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE platform.worker_runs w
    SET status = 'running',
        lease_owner = :worker || ':' || gen_random_uuid()::text,
        lease_until = now() + :lease,
        updated_at = now()
    FROM picked
    WHERE w.id = picked.id
    RETURNING w.id, w.lease_owner
    """
)

_w = worker_runs


def _held(claim: StudioClaim) -> sa.ColumnElement[bool]:
    return sa.and_(
        _w.c.id == claim.run_id,
        _w.c.status == RunStatus.RUNNING.value,
        _w.c.lease_owner == claim.lease_token,
    )


@dataclass(frozen=True)
class SqlStudioRunQueue:
    """Implements `dw_agent_runtime.ports.StudioRunQueuePort`."""

    session_factory: async_sessionmaker[AsyncSession]
    ids: IdGenerator
    clock: UtcClock

    async def _tenant_ids(self, statement: Any, values: dict[str, Any]) -> list[uuid.UUID]:
        async with self.session_factory() as session, session.begin():
            return [row.tenant_id for row in await session.execute(statement, values)]

    async def _bound(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})

    # ---- the studio_runs lane ------------------------------------------

    async def scopes_due(self, limit: int) -> list[uuid.UUID]:
        return await self._tenant_ids(_SCOPES_DUE, {"limit": limit})

    async def claim(
        self, tenant_id: uuid.UUID, *, limit: int, worker: str, lease: timedelta
    ) -> list[StudioClaim]:
        if limit <= 0:
            return []
        async with self.session_factory() as session, session.begin():
            await self._bound(session, tenant_id)
            rows = await session.execute(_CLAIM, {"limit": limit, "worker": worker, "lease": lease})
            return [StudioClaim(tenant_id, row.id, row.lease_owner) for row in rows]

    async def beat(self, claim: StudioClaim, *, lease: timedelta) -> bool:
        async with self.session_factory() as session, session.begin():
            await self._bound(session, claim.tenant_id)
            found = await session.scalar(
                sa.update(_w)
                .where(_held(claim))
                .values(lease_until=sa.func.now() + sa.literal(lease))
                .returning(_w.c.id)
            )
        return found is not None

    async def release(self, claim: StudioClaim) -> bool:
        async with self.session_factory() as session, session.begin():
            await self._bound(session, claim.tenant_id)
            found = await session.scalar(
                sa.update(_w)
                .where(_held(claim))
                .values(
                    status=RunStatus.QUEUED.value,
                    lease_owner=None,
                    lease_until=None,
                    available_at=sa.func.now(),
                    updated_at=sa.func.now(),
                )
                .returning(_w.c.id)
            )
        return found is not None

    # ---- the studio_run_reaper lane ------------------------------------

    async def orphans_due(self, limit: int) -> list[uuid.UUID]:
        return await self._tenant_ids(_ORPHANS_DUE, {"limit": limit})

    async def requeue_orphans(
        self,
        tenant_id: uuid.UUID,
        *,
        max_requeues: int,
        backoff: Callable[[int], timedelta],
    ) -> ReapedRuns:
        requeued = dead = 0
        async with self.session_factory() as session, session.begin():
            await self._bound(session, tenant_id)
            orphans = (
                await session.execute(
                    sa.select(
                        _w.c.id,
                        _w.c.workspace_id,
                        _w.c.attempt,
                        _w.c.trigger_kind,
                        _w.c.requested_by,
                    )
                    .where(
                        _STUDIO,
                        _w.c.status == RunStatus.RUNNING.value,
                        _w.c.lease_until < sa.func.now(),
                    )
                    .order_by(_w.c.lease_until, _w.c.id)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for orphan in orphans:
                if orphan.attempt >= max_requeues:
                    await self._dead_letter(session, tenant_id, orphan)
                    dead += 1
                    continue
                await session.execute(
                    sa.update(_w)
                    .where(_w.c.id == orphan.id)
                    .values(
                        status=RunStatus.QUEUED.value,
                        attempt=_w.c.attempt + 1,
                        lease_owner=None,
                        lease_until=None,
                        available_at=sa.func.now() + sa.literal(backoff(orphan.attempt)),
                        updated_at=sa.func.now(),
                    )
                )
                requeued += 1
        return ReapedRuns(requeued=requeued, dead_lettered=dead)

    async def _dead_letter(self, session: AsyncSession, tenant_id: uuid.UUID, run: Any) -> None:
        """R5.7: the run, its audit and its outbox event, one transaction."""
        await session.execute(
            sa.update(_w)
            .where(_w.c.id == run.id)
            .values(
                status=RunStatus.DEAD_LETTERED.value,
                lease_owner=None,
                lease_until=None,
                error={"code": "dead_lettered", "attempt": int(run.attempt) + 1},
                updated_at=sa.func.now(),
            )
        )
        now = self.clock.now()
        await SqlAuditRepository(session).append(
            lane_audit_event(
                lane=REAPER_LANE,
                event_id=self.ids.new_uuid(),
                tenant_id=TenantId(tenant_id),
                workspace_id=WorkspaceId(run.workspace_id),
                action=_DEAD_LETTERED,
                resource_type="worker_run",
                resource_id=str(run.id),
                occurred_at=now,
                details={"reason_code": "dead_lettered", "attempt": int(run.attempt) + 1},
                run_id=run.id,
            )
        )
        await SqlOutboxRepository(session).add(
            OutboxEvent(
                id=self.ids.new_uuid(),
                tenant_id=TenantId(tenant_id),
                workspace_id=WorkspaceId(run.workspace_id),
                event_type=DEAD_LETTERED_EVENT,
                schema_version="1",
                aggregate_id=run.id,
                occurred_at=now,
                payload={
                    "run_id": str(run.id),
                    "workspace_id": str(run.workspace_id),
                    "requested_by": str(run.requested_by),
                    "trigger_kind": run.trigger_kind,
                },
                actor_id=system_actor(REAPER_LANE).value,
            )
        )

    async def deadlines_due(self, limit: int, *, unclaimed_after: timedelta) -> list[uuid.UUID]:
        return await self._tenant_ids(
            _DEADLINES_DUE, {"limit": limit, "unclaimed_after": unclaimed_after}
        )

    async def cancel_overdue(
        self, tenant_id: uuid.UUID, *, unclaimed_after: timedelta
    ) -> ReapedRuns:
        """The same two cases `studio_run_deadlines_due` finds, under RLS."""
        now_ = sa.func.now()
        overdue = sa.or_(
            sa.and_(
                _w.c.status.in_(_UNFINISHED),
                _w.c.deadline_at <= now_,
                sa.or_(_w.c.lease_until.is_(None), _w.c.lease_until < now_),
            ),
            sa.and_(
                _w.c.status == RunStatus.QUEUED.value,
                _w.c.deadline_at.is_(None),
                _w.c.created_at <= now_ - sa.literal(unclaimed_after),
            ),
        )
        async with self.session_factory() as session, session.begin():
            await self._bound(session, tenant_id)
            runs = (
                await session.execute(
                    sa.select(_w.c.id, _w.c.workspace_id)
                    .where(_STUDIO, overdue)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                await session.execute(
                    sa.update(_w)
                    .where(_w.c.id == run.id)
                    .values(
                        status=RunStatus.CANCELLED.value,
                        lease_owner=None,
                        lease_until=None,
                        error={"code": "deadline_exceeded"},
                        updated_at=now_,
                    )
                )
                await SqlAuditRepository(session).append(
                    lane_audit_event(
                        lane=REAPER_LANE,
                        event_id=self.ids.new_uuid(),
                        tenant_id=TenantId(tenant_id),
                        workspace_id=WorkspaceId(run.workspace_id),
                        action=_DEADLINE_EXCEEDED,
                        resource_type="worker_run",
                        resource_id=str(run.id),
                        occurred_at=self.clock.now(),
                        details={"reason_code": "deadline_exceeded"},
                        run_id=run.id,
                    )
                )
        return ReapedRuns(cancelled=len(runs))
