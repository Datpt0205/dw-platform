"""SQL for the freeze switches (agent-lifecycle R7.4-R7.6, R7.10; migration
8efd60e59d32).

`SqlControlSwitchRepository` runs as `dw_app` under one company's RLS: what
the company sets, asks to lift, and reads, and what the settlement lifts. The
database decides the rest: `uq_control_switches_open` refuses a second open
freeze of one origin or a second open kill of one component,
`uq_approval_requests_control_lift_pending` a second pending lift, and
`platform.guard_control_switch()` any lift but the one an approved,
second-person request names. `control_switch_tx` binds the same statements to
a session another store already holds: a kill is written in the transaction
that read its component (`dw_studio.lifecycle`, agent-lifecycle ticket 05).

`SqlPlatformFreezeRepository` runs as `dw_provisioner` (no tenant, BYPASSRLS):
the operators' switches, each with its `platform.provisioning_audit` row in
the same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, NotFoundError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import (
    SqlApprovalRepository,
    SqlAuditRepository,
    SqlOutboxRepository,
)
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.control_switches import (
    ControlSwitchTx,
    LiftDecision,
    OpenFreeze,
    OpenKill,
    ProvisioningAudit,
    ReasonCode,
    already_frozen,
    already_killed,
)
from dw_platform.application.effect_keys import EffectClaim
from dw_platform.domain.approval import ApprovalRequest
from dw_platform.domain.audit import AuditEvent
from dw_platform.domain.outbox import OutboxEvent

__all__ = ["SqlControlSwitchRepository", "SqlPlatformFreezeRepository", "control_switch_tx"]

_OPEN_INDEX = "uq_control_switches_open"
_LIFT_PENDING_INDEX = "uq_approval_requests_control_lift_pending"
_PLATFORM_OPEN_INDEX = "uq_platform_freezes_open"
_TENANT_FK = "fk_control_switches_tenant_id_tenants"

_SWITCHES = sa.table(
    "control_switches",
    sa.column("id", sa.Uuid),
    sa.column("tenant_id", sa.Uuid),
    sa.column("scope_type"),
    sa.column("owning_workspace_id", sa.Uuid),
    sa.column("target_id", sa.Uuid),
    sa.column("action"),
    sa.column("origin"),
    sa.column("reason_code"),
    sa.column("reason"),
    sa.column("set_by", sa.Uuid),
    sa.column("set_at", sa.DateTime(timezone=True)),
    sa.column("lift_approval_id", sa.Uuid),
    sa.column("lifted_by", sa.Uuid),
    sa.column("lifted_at", sa.DateTime(timezone=True)),
    sa.column("lift_reason"),
    schema="platform",
)
_PLATFORM = sa.table(
    "platform_freezes",
    sa.column("id", sa.Uuid),
    sa.column("reason_code"),
    sa.column("reason"),
    sa.column("set_by", sa.Uuid),
    sa.column("set_at", sa.DateTime(timezone=True)),
    sa.column("lifted_by", sa.Uuid),
    sa.column("lifted_at", sa.DateTime(timezone=True)),
    schema="platform",
)

# A company's freeze: scope `tenant`, either origin, open.
_OPEN_FREEZE = sa.and_(
    _SWITCHES.c.scope_type == "tenant",
    _SWITCHES.c.action == "freeze",
    _SWITCHES.c.lifted_at.is_(None),
)


def _constraint(exc: IntegrityError) -> str:
    """The constraint a refusal names, as the driver reports it."""
    return str(getattr(exc.orig, "constraint_name", None) or exc.orig)


@dataclass
class _Tx:
    """`ControlSwitchTx` over one session bound to one company."""

    session: AsyncSession
    tenant_id: uuid.UUID

    async def open_freezes(self) -> list[OpenFreeze]:
        rows = (
            await self.session.execute(
                sa.select(
                    _SWITCHES.c.id, _SWITCHES.c.origin, _SWITCHES.c.reason_code, _SWITCHES.c.set_at
                )
                .where(_OPEN_FREEZE)
                # The operator's freeze first: it is the one the company cannot lift.
                .order_by(sa.desc(_SWITCHES.c.origin == "platform"), _SWITCHES.c.set_at)
            )
        ).all()
        return [
            OpenFreeze(id=r.id, origin=r.origin, reason_code=r.reason_code, set_at=r.set_at)
            for r in rows
        ]

    async def platform_freeze(self) -> tuple[datetime, str] | None:
        row = (
            await self.session.execute(
                sa.select(_PLATFORM.c.set_at, _PLATFORM.c.reason_code).where(
                    _PLATFORM.c.lifted_at.is_(None)
                )
            )
        ).first()
        return None if row is None else (row.set_at, row.reason_code)

    async def claim(self, claim: EffectClaim) -> None:
        await claim_effect_key(self.session, claim)

    async def insert_freeze(
        self,
        *,
        switch_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        set_by: uuid.UUID,
    ) -> None:
        try:
            await self.session.execute(
                sa.insert(_SWITCHES).values(
                    id=switch_id,
                    tenant_id=self.tenant_id,
                    scope_type="tenant",
                    action="freeze",
                    origin="tenant",
                    reason_code=reason_code,
                    reason=reason,
                    set_by=set_by,
                )
            )
        except IntegrityError as exc:
            if _OPEN_INDEX in _constraint(exc):
                raise already_frozen() from exc
            raise

    async def open_kill(self, target_id: uuid.UUID) -> OpenKill | None:
        row = (
            await self.session.execute(
                sa.select(
                    _SWITCHES.c.id,
                    _SWITCHES.c.target_id,
                    _SWITCHES.c.owning_workspace_id,
                    _SWITCHES.c.set_by,
                ).where(
                    _SWITCHES.c.action == "kill",
                    _SWITCHES.c.target_id == target_id,
                    _SWITCHES.c.lifted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            return None
        return OpenKill(
            id=row.id,
            target_id=row.target_id,
            owning_workspace_id=row.owning_workspace_id,
            set_by=row.set_by,
        )

    async def insert_kill(
        self,
        *,
        switch_id: uuid.UUID,
        scope_type: Literal["agent", "workflow"],
        target_id: uuid.UUID,
        owning_workspace_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        set_by: uuid.UUID,
    ) -> None:
        try:
            await self.session.execute(
                sa.insert(_SWITCHES).values(
                    id=switch_id,
                    tenant_id=self.tenant_id,
                    scope_type=scope_type,
                    owning_workspace_id=owning_workspace_id,
                    target_id=target_id,
                    action="kill",
                    origin="tenant",
                    reason_code=reason_code,
                    reason=reason,
                    set_by=set_by,
                )
            )
        except IntegrityError as exc:
            if _OPEN_INDEX in _constraint(exc):
                raise already_killed() from exc
            raise

    async def announce(self, event: OutboxEvent) -> None:
        await SqlOutboxRepository(self.session).add(event)

    async def open_lift_request(self, request: ApprovalRequest) -> None:
        try:
            await SqlApprovalRepository(self.session).add(request)
        except IntegrityError as exc:
            if _LIFT_PENDING_INDEX in _constraint(exc):
                raise ConflictError(
                    "a request to lift this freeze is already waiting",
                    details={"reason_code": "lift_pending"},
                ) from exc
            raise

    async def lift_decision(
        self, approval_id: uuid.UUID, approval_type: str
    ) -> LiftDecision | None:
        row = (
            await self.session.execute(
                sa.select(
                    tables.approval_requests.c.status,
                    tables.approval_requests.c.payload,
                    tables.approval_requests.c.requested_by,
                    tables.approval_requests.c.workspace_id,
                    tables.approval_decisions.c.decided_by,
                )
                .join(
                    tables.approval_decisions,
                    sa.and_(
                        tables.approval_decisions.c.request_id == tables.approval_requests.c.id,
                        tables.approval_decisions.c.tenant_id
                        == tables.approval_requests.c.tenant_id,
                    ),
                )
                .where(
                    tables.approval_requests.c.id == approval_id,
                    tables.approval_requests.c.approval_type == approval_type,
                )
                .order_by(tables.approval_decisions.c.decided_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        raw = (row.payload or {}).get("switch_id")
        try:
            switch_id = uuid.UUID(str(raw)) if raw is not None else None
        except ValueError:
            switch_id = None
        return LiftDecision(
            approved=row.status == "approved",
            switch_id=switch_id,
            decided_by=row.decided_by,
            requested_by=row.requested_by,
            workspace_id=row.workspace_id,
        )

    async def lift(self, switch_id: uuid.UUID, *, by: uuid.UUID, approval_id: uuid.UUID) -> bool:
        lifted = (
            await self.session.execute(
                sa.update(_SWITCHES)
                .where(_SWITCHES.c.id == switch_id, _SWITCHES.c.lifted_at.is_(None))
                .values(lifted_by=by, lifted_at=sa.func.now(), lift_approval_id=approval_id)
                .returning(_SWITCHES.c.id)
            )
        ).first()
        return lifted is not None

    async def audit(self, event: AuditEvent) -> None:
        await SqlAuditRepository(self.session).append(event)


def control_switch_tx(session: AsyncSession, tenant_id: uuid.UUID) -> ControlSwitchTx:
    """The switch statements on a session already bound to `tenant_id`'s
    RLS, in the transaction its holder opened and commits."""
    return _Tx(session, tenant_id)


@dataclass(frozen=True)
class SqlControlSwitchRepository:
    """Implements `ControlSwitchRepositoryPort` as `dw_app`."""

    session_factory: async_sessionmaker[AsyncSession]

    @asynccontextmanager
    async def transaction(
        self, tenant_id: uuid.UUID, *, workspace_id: uuid.UUID | None = None
    ) -> AsyncIterator[_Tx]:
        scope = TenantScope(tenant_id=tenant_id, workspace_id=workspace_id)
        async with tenant_session(self.session_factory, scope) as session:
            yield _Tx(session, tenant_id)


@dataclass(frozen=True)
class SqlPlatformFreezeRepository:
    """Implements `PlatformFreezeRepositoryPort` as `dw_provisioner`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def set_platform_freeze(
        self,
        *,
        freeze_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        audit: ProvisioningAudit,
    ) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(_PLATFORM).values(
                        id=freeze_id, reason_code=reason_code, reason=reason, set_by=audit.actor_id
                    )
                )
                await _record(session, audit, freeze_id)
        except IntegrityError as exc:
            if _PLATFORM_OPEN_INDEX in _constraint(exc):
                raise already_frozen() from exc
            raise

    async def lift_platform_freeze(
        self, *, by: uuid.UUID, audit: ProvisioningAudit
    ) -> uuid.UUID | None:
        async with self.session_factory() as session, session.begin():
            lifted = await session.scalar(
                sa.update(_PLATFORM)
                .where(_PLATFORM.c.lifted_at.is_(None))
                .values(lifted_by=by, lifted_at=sa.func.now())
                .returning(_PLATFORM.c.id)
            )
            if lifted is not None:
                await _record(session, audit, lifted)
        return lifted

    async def set_tenant_freeze(
        self,
        *,
        tenant_id: uuid.UUID,
        switch_id: uuid.UUID,
        reason_code: ReasonCode,
        reason: str,
        audit: ProvisioningAudit,
    ) -> None:
        try:
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(_SWITCHES).values(
                        id=switch_id,
                        tenant_id=tenant_id,
                        scope_type="tenant",
                        action="freeze",
                        origin="platform",
                        reason_code=reason_code,
                        reason=reason,
                        set_by=audit.actor_id,
                    )
                )
                await _record(session, audit, switch_id)
        except IntegrityError as exc:
            constraint = _constraint(exc)
            if _OPEN_INDEX in constraint:
                raise already_frozen() from exc
            if _TENANT_FK in constraint:
                raise NotFoundError(
                    "unknown tenant", details={"tenant_id": str(tenant_id)}
                ) from exc
            raise

    async def lift_tenant_freeze(
        self,
        *,
        tenant_id: uuid.UUID,
        by: uuid.UUID,
        reason: str | None,
        audit: ProvisioningAudit,
    ) -> uuid.UUID | None:
        async with self.session_factory() as session, session.begin():
            # The operator's row only: the company's own is lifted by two of
            # its people (D11).
            lifted = await session.scalar(
                sa.update(_SWITCHES)
                .where(
                    _SWITCHES.c.tenant_id == tenant_id,
                    _SWITCHES.c.origin == "platform",
                    _OPEN_FREEZE,
                )
                .values(lifted_by=by, lifted_at=sa.func.now(), lift_reason=reason)
                .returning(_SWITCHES.c.id)
            )
            if lifted is not None:
                await _record(session, audit, lifted)
        return lifted


async def _record(session: AsyncSession, audit: ProvisioningAudit, target: uuid.UUID) -> None:
    await session.execute(
        sa.insert(tables.provisioning_audit).values(
            id=audit.id,
            actor_id=audit.actor_id,
            action=audit.action,
            target_type=audit.target_type,
            target_id=str(target),
            details=audit.details,
            occurred_at=audit.occurred_at,
        )
    )
