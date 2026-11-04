"""SQL for the company's Allowed hosts (connections-and-vault R3.7-R3.12,
R3.18, R3.21; migration 20bb9a2210cf).

Every statement runs under the caller's tenant (RLS). Opening a request asks
`platform.checker_candidates` in the same transaction that writes it; a
settlement reads the decided approval and inserts the row `ON CONFLICT DO
NOTHING`, auditing only a row that is new; a removal stamps `removed_at` and
`removed_by` only on a live row. `SqlAllowedHosts` is what the egress client
reads on every call: the live rows of one tenant, nothing cached.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import NotFoundError
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.repositories import SqlApprovalRepository, SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.egress_allowlist import (
    EGRESS_ALLOWED_HOST,
    AllowedHostDecision,
    AllowedHostSettlement,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.allowed_hosts import AllowedHost
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent

__all__ = ["SqlAllowedHostRepository", "SqlAllowedHosts"]

_HOSTS = sa.table(
    "egress_allowed_hosts",
    sa.column("id", sa.Uuid),
    sa.column("tenant_id"),
    sa.column("owning_workspace_id"),
    sa.column("host_pattern"),
    sa.column("ports"),
    sa.column("purpose"),
    sa.column("note"),
    sa.column("created_by"),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("removed_at", sa.DateTime(timezone=True)),
    sa.column("removed_by"),
    schema="platform",
)
_COLUMNS = (
    _HOSTS.c.id,
    _HOSTS.c.host_pattern,
    _HOSTS.c.ports,
    _HOSTS.c.purpose,
    _HOSTS.c.note,
    _HOSTS.c.owning_workspace_id,
    _HOSTS.c.created_by,
    _HOSTS.c.created_at,
)


def _host(row: Any) -> AllowedHost:
    return AllowedHost(
        id=row.id,
        host_pattern=row.host_pattern,
        ports=tuple(row.ports),
        purpose=row.purpose,
        note=row.note,
        owning_workspace_id=row.owning_workspace_id,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _position(host: AllowedHost) -> CursorPosition:
    return CursorPosition(sort_value=host.created_at, tiebreaker=host.id)


def _scope(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)


@dataclass(frozen=True)
class SqlAllowedHostRepository:
    """Implements ``AllowedHostRepositoryPort`` and ``AllowedHostSettlementPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list(self, context: AccessContext, request: PageRequest) -> Page[AllowedHost]:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            rows = (
                await session.execute(
                    sa.select(*_COLUMNS)
                    .where(
                        _HOSTS.c.removed_at.is_(None),
                        after_position(_HOSTS.c.created_at, _HOSTS.c.id, request.after),
                    )
                    .order_by(*newest_first(_HOSTS.c.created_at, _HOSTS.c.id))
                    .limit(request.fetch_limit)
                )
            ).all()
        return build_page([_host(row) for row in rows], request=request, position_of=_position)

    async def open_request(
        self, context: AccessContext, request: ApprovalRequest, *, audit: AuditEvent
    ) -> bool:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            checker = (
                await session.execute(
                    sa.text("SELECT 1 FROM platform.checker_candidates(:t, :k, :p, :w) LIMIT 1"),
                    {
                        "t": context.tenant_id,
                        "k": request.required_scope,
                        "p": context.principal_id,
                        "w": request.workspace_id.value,
                    },
                )
            ).first()
            if checker is None:
                return False
            await SqlApprovalRepository(session).add(request)
            await SqlAuditRepository(session).append(audit)
        return True

    async def remove(
        self,
        context: AccessContext,
        host_id: uuid.UUID,
        *,
        audit_for: Callable[[AllowedHost], AuditEvent],
    ) -> AllowedHost | None:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            row = (
                await session.execute(
                    sa.update(_HOSTS)
                    .where(_HOSTS.c.id == host_id, _HOSTS.c.removed_at.is_(None))
                    .values(removed_at=sa.func.now(), removed_by=context.principal_id)
                    .returning(*_COLUMNS)
                )
            ).first()
            if row is None:
                return None
            removed = _host(row)
            await SqlAuditRepository(session).append(audit_for(removed))
        return removed

    async def settle(
        self,
        scope: WorkScope,
        approval_id: uuid.UUID,
        settle: Callable[[AllowedHostDecision], AllowedHostSettlement],
    ) -> AllowedHostSettlement:
        r, d = tables.approval_requests, tables.approval_decisions
        bound = TenantScope(tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
        async with tenant_session(self.session_factory, bound) as session:
            decided = (
                await session.execute(
                    sa.select(
                        r.c.payload,
                        r.c.requested_by,
                        r.c.workspace_id,
                        d.c.outcome,
                        d.c.decided_by,
                    )
                    .select_from(r.join(d, d.c.request_id == r.c.id))
                    .where(r.c.id == approval_id, r.c.approval_type == EGRESS_ALLOWED_HOST)
                )
            ).first()
            if decided is None:
                raise NotFoundError(
                    "no decided allowed-host approval of that id",
                    details={"approval_id": str(approval_id)},
                )
            payload = dict(decided.payload)
            try:
                decision = AllowedHostDecision(
                    approval_id=approval_id,
                    approved=decided.outcome == "approved",
                    decided_by=decided.decided_by,
                    requested_by=decided.requested_by,
                    workspace_id=decided.workspace_id,
                    host_pattern=str(payload["host_pattern"]),
                    ports=tuple(int(p) for p in payload["ports"]),
                    purpose=str(payload["purpose"]),
                    note=None if payload.get("note") is None else str(payload["note"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise NotFoundError(
                    "the approval names no allowed host",
                    details={"approval_id": str(approval_id)},
                ) from exc
            settlement = settle(decision)
            if settlement.row is None:
                return settlement
            row = settlement.row
            inserted = (
                await session.execute(
                    sa.text(
                        "INSERT INTO platform.egress_allowed_hosts (id, tenant_id,"
                        " owning_workspace_id, host_pattern, ports, purpose, note, created_by)"
                        " VALUES (:id, :t, :w, :pattern, :ports, :purpose, :note, :by)"
                        # Either key: the approval's id again (a replay, even of
                        # a removed row), or a live row of the same pattern and
                        # purpose (another approval's). Neither adds a row.
                        " ON CONFLICT DO NOTHING RETURNING id"
                    ),
                    {
                        "id": row.id,
                        "t": scope.tenant_id,
                        "w": row.owning_workspace_id,
                        "pattern": row.host_pattern,
                        "ports": list(row.ports),
                        "purpose": row.purpose,
                        "note": row.note,
                        "by": row.created_by,
                    },
                )
            ).first()
            if inserted is None:
                return AllowedHostSettlement("already_present")
            if settlement.audit is not None:
                await SqlAuditRepository(session).append(settlement.audit)
        return settlement


@dataclass(frozen=True)
class _LiveRule:
    host_pattern: str
    ports: tuple[int, ...]
    purpose: str


@dataclass(frozen=True)
class SqlAllowedHosts:
    """Implements `dw_connectors.egress.AllowedHostsPort`: the live rows of one
    tenant, read on every call."""

    session_factory: async_sessionmaker[AsyncSession]

    async def live(self, tenant_id: uuid.UUID) -> Sequence[_LiveRule]:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            rows = (
                await session.execute(
                    sa.select(_HOSTS.c.host_pattern, _HOSTS.c.ports, _HOSTS.c.purpose).where(
                        _HOSTS.c.removed_at.is_(None)
                    )
                )
            ).all()
        return [_LiveRule(row.host_pattern, tuple(row.ports), row.purpose) for row in rows]
