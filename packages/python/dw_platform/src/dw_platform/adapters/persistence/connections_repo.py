"""SQL for the shared connections (connections-and-vault R1.15, R5; migrations
70d8a4564454 and 388a31c46bdf).

`SqlConnectionStore.transaction` opens one transaction under one company's RLS
(`tenant_session`), its principal kept for `platform.workspace_reach`; both
`ConnectionService` and `ConnectionUsability` read through it, so a list, a
write and the rule ask the same depth owner. The database holds the rules a
row can break: the status table and the enable's approval
(`guard_connection_status`), the one live account (`uq_connections_account_live`)
and the revocation's company (`revoke_connection_secrets`); this module reads
their refusals back by constraint name.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_kernel.pagination import PageRequest
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.keyset import after_position, newest_first
from dw_platform.adapters.persistence.repositories import SqlApprovalRepository, SqlAuditRepository
from dw_platform.adapters.persistence.secret_envelopes import SqlSecretEnvelopes
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.connection_admin import (
    CONNECTIONS_ENABLE,
    EnableDecision,
    Revocation,
)
from dw_platform.application.connections import Connection
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.application.secrets import SecretSubject, SecretVersionStatus
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent

__all__ = ["SqlConnectionStore", "SqlConnectionTx"]

_CONNECTIONS = sa.table(
    "connections",
    sa.column("id", sa.Uuid),
    sa.column("tenant_id", sa.Uuid),
    sa.column("owning_workspace_id", sa.Uuid),
    sa.column("name"),
    sa.column("connector_key"),
    sa.column("connector_major"),
    sa.column("share_scope"),
    sa.column("external_account"),
    sa.column("status"),
    sa.column("scopes"),
    sa.column("last_used_at", sa.DateTime(timezone=True)),
    sa.column("created_by", sa.Uuid),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("disabled_at", sa.DateTime(timezone=True)),
    sa.column("compromised_at", sa.DateTime(timezone=True)),
    schema="platform",
)
_COLUMNS = tuple(_CONNECTIONS.c)

# The refusal `POST` reads back as `connection_exists` (R5.21).
ACCOUNT_LIVE = "uq_connections_account_live"
# The status trigger's two refusals (migration 388a31c46bdf).
_STATUS_REFUSALS = frozenset({"ck_connections_status_transition", "ck_connections_enable_approved"})

_REACH = sa.text("SELECT platform.workspace_reach(:t, :u, :k) AS w")
_CHECKER = sa.text("SELECT 1 FROM platform.checker_candidates(:t, :k, :p, :w) LIMIT 1")
_REVOKE = sa.text("SELECT compromised_on, versions FROM platform.revoke_connection_secrets(:id)")
_ENABLE_APPROVAL = sa.text("SELECT set_config('app.connection_enable_approval', :a, true)")


def _connection(row: Any) -> Connection:
    return Connection(
        id=row.id,
        tenant_id=row.tenant_id,
        owning_workspace_id=row.owning_workspace_id,
        name=row.name,
        connector_key=row.connector_key,
        connector_major=row.connector_major,
        share_scope=row.share_scope,
        external_account=row.external_account,
        status=row.status,
        scopes=tuple(row.scopes or ()),
        last_used_at=row.last_used_at,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        disabled_at=row.disabled_at,
        compromised_at=row.compromised_at,
    )


@dataclass
class SqlConnectionTx:
    """Implements `ConnectionTx` (and `UsabilityTx`) on one open transaction."""

    session: AsyncSession
    tenant_id: uuid.UUID
    principal_id: uuid.UUID | None

    async def connection(self, connection_id: uuid.UUID, *, lock: bool) -> Connection | None:
        query = sa.select(*_COLUMNS).where(_CONNECTIONS.c.id == connection_id)
        if lock:
            query = query.with_for_update()
        row = (await self.session.execute(query)).first()
        return None if row is None else _connection(row)

    async def reach(self, key: str) -> frozenset[uuid.UUID]:
        if self.principal_id is None:
            return frozenset()
        rows = await self.session.execute(
            _REACH, {"t": self.tenant_id, "u": self.principal_id, "k": key}
        )
        return frozenset(rows.scalars())

    async def secret_versions(
        self, connection_id: uuid.UUID, secret_field: str
    ) -> Sequence[SecretVersionStatus]:
        return await SqlSecretEnvelopes(self.session).status(
            SecretSubject("connection", connection_id), secret_field
        )

    async def database_now(self) -> datetime:
        now = await self.session.scalar(sa.select(sa.func.now()))
        assert isinstance(now, datetime)
        return now

    async def page(self, request: PageRequest, read_key: str) -> Sequence[Connection]:
        if self.principal_id is None:
            return []
        reach = sa.select(
            sa.func.platform.workspace_reach(
                sa.cast(self.tenant_id, sa.Uuid), sa.cast(self.principal_id, sa.Uuid), read_key
            )
        ).scalar_subquery()
        rows = await self.session.execute(
            sa.select(*_COLUMNS)
            .where(
                _CONNECTIONS.c.owning_workspace_id.in_(reach),
                after_position(_CONNECTIONS.c.created_at, _CONNECTIONS.c.id, request.after),
            )
            .order_by(*newest_first(_CONNECTIONS.c.created_at, _CONNECTIONS.c.id))
            .limit(request.fetch_limit)
        )
        return [_connection(row) for row in rows]

    async def insert(self, row: Connection) -> None:
        values = dataclasses.asdict(row)
        # The database's own: the trigger refuses either at INSERT, and the
        # list's order is the time of the commit's transaction.
        for column in ("disabled_at", "compromised_at", "created_at", "updated_at"):
            values.pop(column)
        values["scopes"] = list(row.scopes)
        try:
            await self.session.execute(sa.insert(_CONNECTIONS).values(**values))
        except IntegrityError as exc:
            refused = refusal(exc)
            if refused is not None and refused[0] == ACCOUNT_LIVE:
                raise ConflictError(
                    "a connection for this account already exists",
                    details={"reason_code": "connection_exists"},
                ) from None
            raise

    async def rename(self, connection_id: uuid.UUID, name: str) -> None:
        await self.session.execute(
            sa.update(_CONNECTIONS).where(_CONNECTIONS.c.id == connection_id).values(name=name)
        )

    async def set_status(
        self,
        connection_id: uuid.UUID,
        status: str,
        *,
        enable_approval: uuid.UUID | None = None,
    ) -> None:
        if enable_approval is not None:
            (await self.session.execute(_ENABLE_APPROVAL, {"a": str(enable_approval)})).first()
        try:
            await self.session.execute(
                sa.update(_CONNECTIONS)
                .where(_CONNECTIONS.c.id == connection_id)
                .values(status=status)
            )
        except IntegrityError as exc:
            refused = refusal(exc)
            if refused is not None and refused[0] in _STATUS_REFUSALS:
                raise ConflictError(
                    "the connection's status does not move that way",
                    details={"reason_code": "connection_status_refused", "status": status},
                ) from None
            raise

    async def delete(self, connection_id: uuid.UUID) -> None:
        await self.session.execute(
            sa.delete(_CONNECTIONS).where(_CONNECTIONS.c.id == connection_id)
        )

    async def revoke_secrets(self, connection_id: uuid.UUID) -> Revocation | None:
        row = (await self.session.execute(_REVOKE, {"id": connection_id})).first()
        return None if row is None else Revocation(row.compromised_on, row.versions)

    async def pending_enable(self, connection_id: uuid.UUID) -> uuid.UUID | None:
        r = tables.approval_requests
        found = await self.session.scalar(
            sa.select(r.c.id)
            .where(
                r.c.approval_type == CONNECTIONS_ENABLE,
                r.c.status == "pending",
                r.c.payload["connection_id"].astext == str(connection_id),
            )
            .order_by(r.c.created_at)
            .limit(1)
        )
        return found if isinstance(found, uuid.UUID) else None

    async def has_checker(self, key: str, proposer: uuid.UUID, workspace: uuid.UUID) -> bool:
        found = (
            await self.session.execute(
                _CHECKER, {"t": self.tenant_id, "k": key, "p": proposer, "w": workspace}
            )
        ).first()
        return found is not None

    async def open_approval(self, request: ApprovalRequest) -> None:
        # Read now, after the row lock: a disable that committed while this
        # transaction waited for the lock is older than the request (the
        # trigger and the settler both compare `created_at > disabled_at`).
        stamped = await self.session.scalar(sa.select(sa.func.clock_timestamp()))
        assert isinstance(stamped, datetime)
        await SqlApprovalRepository(self.session).add(
            dataclasses.replace(request, created_at=stamped)
        )

    async def enable_decision(self, approval_id: uuid.UUID) -> EnableDecision | None:
        r, d = tables.approval_requests, tables.approval_decisions
        row = (
            await self.session.execute(
                sa.select(
                    r.c.payload, r.c.requested_by, r.c.created_at, d.c.outcome, d.c.decided_by
                )
                .select_from(r.join(d, d.c.request_id == r.c.id))
                .where(r.c.id == approval_id, r.c.approval_type == CONNECTIONS_ENABLE)
            )
        ).first()
        if row is None:
            return None
        raw = (row.payload or {}).get("connection_id")
        try:
            connection_id = uuid.UUID(str(raw)) if raw is not None else None
        except ValueError:
            connection_id = None
        return EnableDecision(
            approval_id=approval_id,
            approved=row.outcome == "approved",
            decided_by=row.decided_by,
            requested_by=row.requested_by,
            connection_id=connection_id,
            created_at=row.created_at,
        )

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)

    def secrets(self) -> SqlSecretEnvelopes:
        return SqlSecretEnvelopes(self.session)


@dataclass(frozen=True)
class SqlConnectionStore:
    """Implements `ConnectionStorePort` and `UsabilityStorePort`."""

    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def transaction(
        self,
        tenant_id: uuid.UUID,
        *,
        workspace_id: uuid.UUID | None,
        principal_id: uuid.UUID | None,
    ) -> AsyncIterator[SqlConnectionTx]:
        scope = TenantScope(
            tenant_id=tenant_id, workspace_id=workspace_id, principal_id=principal_id
        )
        async with tenant_session(self.session_factory, scope) as session:
            yield SqlConnectionTx(session, tenant_id, principal_id)
