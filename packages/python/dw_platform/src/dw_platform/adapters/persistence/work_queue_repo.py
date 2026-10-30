"""SQL implementation of the work queue (digital-worker R3, R4).

Every statement runs under the scope's tenant and workspace RLS. A status
changes only by a conditional UPDATE naming the states the application's table
allows it to come from; the CHECKs on the table hold what a row must look like
in each state. The lane's claim takes due items `FOR UPDATE SKIP LOCKED` and
their DW `FOR SHARE`, so a DW being retired (`FOR UPDATE` on its row) and a
claim of its work wait for one another rather than cross (R1.12).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.work_queue import Claimed, WorkListFilter, WorkScope
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.work_item import HandoffPacket, WorkItem, WorkStatus, sources_of

_W = tables.work_items
_DW = tables.digital_workers
_P = tables.service_principals


def _bound(scope: WorkScope) -> TenantScope:
    return TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)


def item_of(row: sa.Row[Any]) -> WorkItem:
    handoff = row.handoff
    return WorkItem(
        id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        dw_id=row.dw_id,
        kind=row.kind,
        source_key=row.source_key,
        payload=dict(row.payload),
        payload_hash=row.payload_hash,
        holder_kind=row.holder_kind,
        holder_id=row.holder_id,
        status=cast(WorkStatus, row.status),
        available_at=row.available_at,
        run_id=row.run_id,
        wake_at=row.wake_at,
        handoff=HandoffPacket(**handoff) if handoff else None,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
    )


def _position(item: WorkItem) -> CursorPosition:
    return CursorPosition(sort_value=item.created_at, tiebreaker=item.id)


@dataclass(frozen=True)
class SqlWorkQueueRepository:
    """Implements ``WorkQueueRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def insert(
        self,
        scope: WorkScope,
        item: WorkItem,
        *,
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            inserted = (
                await session.execute(
                    pg_insert(_W)
                    .values(
                        id=item.id,
                        tenant_id=item.tenant_id,
                        workspace_id=item.workspace_id,
                        dw_id=item.dw_id,
                        kind=item.kind,
                        source_key=item.source_key,
                        payload=dict(item.payload),
                        payload_hash=item.payload_hash,
                        holder_kind=item.holder_kind,
                        holder_id=item.holder_id,
                        status=item.status,
                        available_at=item.available_at,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                    )
                    .on_conflict_do_nothing(constraint="uq_work_items_source")
                    .returning(_W)
                )
            ).first()
            if inserted is None:
                inserted = (
                    await session.execute(
                        sa.select(_W).where(
                            _W.c.tenant_id == item.tenant_id,
                            _W.c.dw_id == item.dw_id,
                            _W.c.kind == item.kind,
                            _W.c.source_key == item.source_key,
                        )
                    )
                ).one()
            elif audit is not None:
                await SqlAuditRepository(session).append(audit)
            # After the row is known: a repeat of the source answers with the
            # item that already holds it (R3.4), so its key names that item;
            # a different payload is refused by the caller, and claims nothing.
            if effect is not None and inserted.payload_hash == item.payload_hash:
                await claim_effect_key(session, effect.of(inserted.id))
        return item_of(inserted)

    async def get(self, scope: WorkScope, item_id: uuid.UUID) -> WorkItem | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (await session.execute(sa.select(_W).where(_W.c.id == item_id))).first()
        return None if row is None else item_of(row)

    async def page(
        self, scope: WorkScope, request: PageRequest, where: WorkListFilter
    ) -> Page[WorkItem]:
        clauses: list[sa.ColumnElement[bool]] = [
            _W.c.workspace_id == scope.workspace_id,
            after_position(_W.c.created_at, _W.c.id, request.after),
        ]
        if where.status is not None:
            clauses.append(_W.c.status == where.status)
        if where.holder_kind is not None:
            clauses.append(_W.c.holder_kind == where.holder_kind)
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            rows = (
                await session.execute(
                    sa.select(_W)
                    .where(*clauses)
                    .order_by(*newest_first(_W.c.created_at, _W.c.id))
                    .limit(request.fetch_limit)
                )
            ).all()
        return build_page([item_of(r) for r in rows], request=request, position_of=_position)

    async def move(
        self,
        scope: WorkScope,
        item_id: uuid.UUID,
        *,
        sources: frozenset[WorkStatus],
        target: WorkStatus,
        values: Mapping[str, object],
        audit: AuditEvent | None,
        effect: PendingEffect | None = None,
    ) -> WorkItem | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            if effect is not None:
                await claim_effect_key(session, effect.of(item_id))
            row = (
                await session.execute(
                    sa.update(_W)
                    .where(_W.c.id == item_id, _W.c.status.in_(sorted(sources)))
                    .values(status=target, **values)
                    .returning(_W)
                )
            ).first()
            if row is None:
                return None
            if audit is not None:
                await SqlAuditRepository(session).append(audit)
        return item_of(row)

    async def due_scopes(self, *, limit: int) -> list[WorkScope]:
        # No transaction setting: the function is the one cross-tenant read,
        # and returns ids only (migration cfbd906be98b).
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.text("SELECT tenant_id, workspace_id FROM platform.dw_work_scopes_due(:n)"),
                    {"n": limit},
                )
            ).all()
        return [WorkScope(tenant_id=r.tenant_id, workspace_id=r.workspace_id) for r in rows]

    async def claim_due(
        self,
        scope: WorkScope,
        *,
        limit: int,
        audit_of: Callable[[WorkItem, uuid.UUID], AuditEvent],
    ) -> list[Claimed]:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            due = (
                await session.execute(
                    sa.select(_W.c.id, _W.c.run_id)
                    .select_from(
                        _W.join(_DW, _DW.c.id == _W.c.dw_id).join(
                            _P, _P.c.user_id == _DW.c.principal_user_id
                        )
                    )
                    .where(
                        _W.c.status == "open",
                        _W.c.available_at <= sa.func.now(),
                        _DW.c.state == "operating",
                        _P.c.owner_user_id.is_not(None),
                    )
                    .order_by(_W.c.available_at, _W.c.id)
                    .limit(limit)
                    .with_for_update(of=_W, skip_locked=True)
                )
            ).all()
            if not due:
                return []
            # The DWs of what was taken, shared: a retirement holds its DW
            # `FOR UPDATE` and waits for this transaction, or this one for it.
            await session.execute(
                sa.select(_DW.c.id)
                .where(_DW.c.id.in_(sa.select(_W.c.dw_id).where(_W.c.id.in_([r.id for r in due]))))
                .with_for_update(read=True)
            )
            claimed: list[Claimed] = []
            for row in due:
                run_id = row.run_id or uuid.uuid4()
                moved = (
                    await session.execute(
                        sa.update(_W)
                        .where(
                            _W.c.id == row.id,
                            _W.c.status.in_(sorted(sources_of("in_progress", "lane"))),
                        )
                        .values(status="in_progress", run_id=run_id)
                        .returning(_W)
                    )
                ).first()
                if moved is not None:
                    item = item_of(moved)
                    await SqlAuditRepository(session).append(audit_of(item, run_id))
                    claimed.append(Claimed(item=item, run_id=run_id))
        return claimed

    async def release_stuck(self, scope: WorkScope, *, older_than: timedelta) -> int:
        runs = sa.table("worker_runs", sa.column("id"), schema="platform")
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            released = await session.execute(
                sa.update(_W)
                .where(
                    _W.c.status == "in_progress",
                    _W.c.updated_at <= sa.func.now() - older_than,
                    ~sa.exists().where(runs.c.id == _W.c.run_id),
                )
                .values(status="open")
            )
        return int(released.rowcount or 0)  # type: ignore[attr-defined]

    async def by_run(self, scope: WorkScope, run_id: uuid.UUID) -> WorkItem | None:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            row = (await session.execute(sa.select(_W).where(_W.c.run_id == run_id))).first()
        return None if row is None else item_of(row)

    async def due_timer_scopes(self, *, limit: int) -> list[WorkScope]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.text("SELECT tenant_id, workspace_id FROM platform.dw_timer_scopes_due(:n)"),
                    {"n": limit},
                )
            ).all()
        return [WorkScope(tenant_id=r.tenant_id, workspace_id=r.workspace_id) for r in rows]

    async def claim_timers(
        self, scope: WorkScope, *, limit: int, lease: timedelta
    ) -> list[WorkItem]:
        async with tenant_session(self.session_factory, _bound(scope)) as session:
            due = (
                await session.execute(
                    sa.select(_W.c.id)
                    .select_from(_W.join(_DW, _DW.c.id == _W.c.dw_id))
                    .where(
                        _W.c.status == "waiting_timer",
                        _W.c.wake_at <= sa.func.now(),
                        _DW.c.state == "operating",
                    )
                    .order_by(_W.c.wake_at, _W.c.id)
                    .limit(limit)
                    .with_for_update(of=_W, skip_locked=True)
                )
            ).all()
            if not due:
                return []
            rows = (
                await session.execute(
                    sa.update(_W)
                    .where(_W.c.id.in_([r.id for r in due]), _W.c.status == "waiting_timer")
                    .values(wake_at=sa.func.now() + lease)
                    .returning(_W)
                )
            ).all()
        return [item_of(r) for r in rows]
