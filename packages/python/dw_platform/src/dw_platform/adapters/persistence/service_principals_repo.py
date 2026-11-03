"""SQL implementation of the service-account ports (org-and-principals R6).

Every statement runs under the caller's tenant RLS. "Not a Digital Worker's
principal" is `platform.is_digital_worker_principal`, never a NOT EXISTS under
the caller's RLS: `platform.digital_workers` is narrowed by workspace, and a DW
of another workspace would pass one. A refusal the database makes is read back
by the constraint it names.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError, DomainError, DWError
from dw_kernel.pagination import CursorPosition, Page, PageRequest, build_page
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.effect_key_store import claim_effect_key
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.adapters.persistence.tenant_member_rows import ensure_tenant_member
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.effect_keys import PendingEffect
from dw_platform.application.service_principals import (
    SERVICE_PRINCIPALS_MANAGE_SCOPE,
    SERVICE_PRINCIPALS_USE_SCOPE,
    BindingFacts,
    MemberStatus,
    MissingGrant,
    NewServicePrincipal,
    ServicePrincipal,
    ServicePrincipalChanges,
)
from dw_platform.domain.audit import AuditEvent

_P = tables.service_principals
_TM = tables.tenant_members

_NAME_TAKEN = "uq_service_principals_tenant_id_name"
_OWNER = "ck_service_principals_accountable_owner"
_NOT_CRITICAL = "ck_role_assignments_service_not_critical"


def service_principal_refusal(error: IntegrityError) -> DWError | None:
    """The domain error a database refusal on a service account stands for, or
    None: 409 `service_principal_name_taken`, 422 `owner_not_member`, 422
    `role_not_allowed_for_service`. Shared by every writer that meets them (this
    adapter, DW creation, the membership routes), so one constraint is one answer."""
    refused = refusal(error)
    if refused is None:
        return None
    if refused[0] == _NAME_TAKEN:
        return ConflictError(
            "this company already has a service account of that name",
            details={"reason_code": "service_principal_name_taken"},
        )
    if refused[0] == _OWNER:
        return DomainError(
            "the accountable owner is an active human member of this company",
            details={"reason_code": "owner_not_member"},
        )
    if refused[0] == _NOT_CRITICAL:
        return DomainError(
            "a service account holds no critical role",
            details={"reason_code": "role_not_allowed_for_service"},
        )
    return None


def _scope(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)


def _reach(context: AccessContext, permission_key: str) -> sa.Select[Any]:
    """The workspaces `platform.workspace_reach` says the caller reaches with the key."""
    return sa.select(
        sa.func.platform.workspace_reach(context.tenant_id, context.principal_id, permission_key)
    )


def _not_a_dw_principal() -> sa.ColumnElement[bool]:
    return sa.not_(sa.func.platform.is_digital_worker_principal(_P.c.user_id, type_=sa.Boolean))


def _select() -> sa.Select[Any]:
    return sa.select(
        _P.c.user_id,
        _P.c.name,
        _P.c.description,
        _P.c.owning_workspace_id,
        _P.c.owner_user_id,
        _TM.c.status,
        sa.not_(
            sa.func.platform.accountable_owner_present(
                _P.c.tenant_id, _P.c.user_id, type_=sa.Boolean
            )
        ).label("owner_missing"),
    ).select_from(
        _P.outerjoin(_TM, sa.and_(_TM.c.tenant_id == _P.c.tenant_id, _TM.c.user_id == _P.c.user_id))
    )


def _principal(row: sa.Row[Any]) -> ServicePrincipal:
    return ServicePrincipal(
        id=row.user_id,
        name=row.name,
        description=row.description,
        owning_workspace_id=row.owning_workspace_id,
        owner_user_id=row.owner_user_id,
        owner_missing=bool(row.owner_missing),
        status=cast(MemberStatus | None, row.status),
    )


def _position(principal: ServicePrincipal) -> CursorPosition:
    return CursorPosition(sort_value=principal.name, tiebreaker=principal.id)


@dataclass(frozen=True)
class SqlServicePrincipalRepository:
    """Implements ``ServicePrincipalRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def workspace_usable(self, context: AccessContext, workspace_id: uuid.UUID) -> bool:
        w = tables.workspaces
        async with tenant_session(self.session_factory, _scope(context)) as session:
            found = await session.scalar(
                sa.select(sa.literal(True)).where(w.c.id == workspace_id, w.c.archived_at.is_(None))
            )
        return bool(found)

    async def reaches(
        self, context: AccessContext, permission_key: str, workspace_id: uuid.UUID
    ) -> bool:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            found = await session.scalar(
                sa.select(sa.literal(workspace_id).in_(_reach(context, permission_key)))
            )
        return bool(found)

    async def create(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        command: NewServicePrincipal,
        *,
        audit: AuditEvent,
        effect: PendingEffect | None = None,
    ) -> None:
        try:
            async with tenant_session(self.session_factory, _scope(context)) as session:
                if effect is not None:
                    await claim_effect_key(session, effect.of(principal_id))
                # The tenant is the access context's, never the request's (step 1).
                await session.execute(
                    sa.insert(tables.users).values(
                        id=principal_id,
                        subject=f"service:{principal_id}",
                        email=None,
                        display_name=command.name,
                        kind="service",
                        owner_tenant_id=context.tenant_id,
                    )
                )
                await session.execute(
                    ensure_tenant_member(context.tenant_id, principal_id, "active")
                )
                await session.execute(
                    sa.insert(_P).values(
                        user_id=principal_id,
                        tenant_id=context.tenant_id,
                        owning_workspace_id=command.owning_workspace_id,
                        name=command.name,
                        description=command.description,
                        owner_user_id=command.owner_user_id,
                        created_by=context.principal_id,
                    )
                )
                # No role: roles come through the role-assignment API (D11).
                await session.execute(
                    sa.insert(tables.memberships).values(
                        id=uuid.uuid4(),
                        tenant_id=context.tenant_id,
                        workspace_id=command.owning_workspace_id,
                        user_id=principal_id,
                    )
                )
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            known = service_principal_refusal(exc)
            if known is not None:
                raise known from exc
            raise

    async def get(self, context: AccessContext, principal_id: uuid.UUID) -> ServicePrincipal | None:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            row = (
                await session.execute(
                    _select().where(_P.c.user_id == principal_id, _not_a_dw_principal())
                )
            ).first()
        return None if row is None else _principal(row)

    async def update(
        self,
        context: AccessContext,
        principal_id: uuid.UUID,
        changes: ServicePrincipalChanges,
        *,
        audit: AuditEvent,
    ) -> bool:
        values: dict[str, object] = {}
        if changes.name is not None:
            values["name"] = changes.name
        if changes.clear_description:
            values["description"] = None
        elif changes.description is not None:
            values["description"] = changes.description
        if changes.owner_user_id is not None:
            values["owner_user_id"] = changes.owner_user_id
        try:
            async with tenant_session(self.session_factory, _scope(context)) as session:
                statement = sa.update(_P).where(_P.c.user_id == principal_id, _not_a_dw_principal())
                # Nothing named still answers whether the row is there.
                statement = (
                    statement.values(**values) if values else statement.values(user_id=_P.c.user_id)
                )
                touched = (await session.execute(statement.returning(_P.c.user_id))).first()
                if touched is None:
                    return False
                await SqlAuditRepository(session).append(audit)
        except IntegrityError as exc:
            known = service_principal_refusal(exc)
            if known is not None:
                raise known from exc
            raise
        return True

    async def page(self, context: AccessContext, request: PageRequest) -> Page[ServicePrincipal]:
        after = request.after
        reached = sa.union(
            _reach(context, SERVICE_PRINCIPALS_MANAGE_SCOPE),
            _reach(context, SERVICE_PRINCIPALS_USE_SCOPE),
        )
        statement = (
            _select()
            .where(_not_a_dw_principal(), _P.c.owning_workspace_id.in_(reached))
            # A name is unique in its company (`uq_service_principals_tenant_id_name`),
            # so it orders alone and that index, led by the tenant RLS binds,
            # carries the page; the cursor's id breaks no tie here.
            .order_by(_P.c.name)
            .limit(request.fetch_limit)
        )
        if after is not None:
            statement = statement.where(_P.c.name > sa.literal(after.sort_value, sa.Text))
        async with tenant_session(self.session_factory, _scope(context)) as session:
            rows = (await session.execute(statement)).all()
        return build_page([_principal(row) for row in rows], request=request, position_of=_position)


# The facts of each id in one statement, under the caller's RLS: a row of
# another tenant, a human (never in `service_principals`) and an unknown id are
# all `found = false`.
_FACTS = sa.text(
    """
    SELECT ids.id AS principal_id,
           p.user_id IS NOT NULL AS found,
           platform.is_digital_worker_principal(ids.id) AS is_dw,
           p.owning_workspace_id,
           coalesce(p.owning_workspace_id IN (
               SELECT platform.workspace_reach(CAST(:t AS uuid), CAST(:me AS uuid), :use)
           ), false) AS can_use,
           coalesce(tm.status = 'active', false) AS active,
           platform.accountable_owner_present(CAST(:t AS uuid), ids.id) AS owner_present,
           coalesce((
               SELECT jsonb_agg(jsonb_build_array(g.permission_key, g.depth, g.anchor_workspace_id)
                                ORDER BY g.permission_key, g.depth, g.anchor_workspace_id)
               FROM platform.uncovered_grants(CAST(:t AS uuid), CAST(:me AS uuid), ids.id) g
           ), '[]'::jsonb) AS uncovered
    FROM unnest(CAST(:ids AS uuid[])) AS ids(id)
    LEFT JOIN platform.service_principals p ON p.user_id = ids.id
    LEFT JOIN platform.tenant_members tm
      ON tm.tenant_id = p.tenant_id AND tm.user_id = p.user_id
    """
)


@dataclass(frozen=True)
class SqlBindingFacts:
    """Implements ``BindingFactsPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def binding_facts(
        self, context: AccessContext, principal_ids: Sequence[uuid.UUID]
    ) -> Mapping[uuid.UUID, BindingFacts]:
        async with tenant_session(self.session_factory, _scope(context)) as session:
            rows = (
                await session.execute(
                    _FACTS,
                    {
                        "t": str(context.tenant_id),
                        "me": str(context.principal_id),
                        "use": SERVICE_PRINCIPALS_USE_SCOPE,
                        "ids": [str(i) for i in principal_ids],
                    },
                )
            ).all()
        return {
            row.principal_id: BindingFacts(
                found=bool(row.found),
                is_digital_worker=bool(row.is_dw),
                owning_workspace_id=row.owning_workspace_id,
                can_use=bool(row.can_use),
                active=bool(row.active),
                owner_present=bool(row.owner_present),
                uncovered=tuple(
                    MissingGrant(key, depth, uuid.UUID(anchor))
                    for key, depth, anchor in row.uncovered
                ),
            )
            for row in rows
        }


__all__ = [
    "SqlBindingFacts",
    "SqlServicePrincipalRepository",
    "service_principal_refusal",
]
