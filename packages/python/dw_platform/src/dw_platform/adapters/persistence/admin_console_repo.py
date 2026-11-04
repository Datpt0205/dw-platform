"""SQL implementation of the Org Admin console repository.

Tenant-scoped reads and writes go through ``tenant_session`` so RLS bounds them
to the caller's tenant, and every query also filters ``tenant_id`` explicitly —
a belt beside the RLS brace, so a workspace or tenant row from elsewhere can
never be read or written even if a policy were ever loosened. The role catalog
is global configuration (no tenant column) and uses a plain session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.admin_console import (
    PermissionInfo,
    PermissionSetInfo,
    TenantSettings,
    UpdateTenantSettings,
    WorkspaceRef,
    WorkspaceSummary,
)
from dw_platform.domain.audit import AuditEvent

_WORKSPACE_SLUG_CONSTRAINT = "uq_workspaces_tenant_slug"


# The catalogue with, for the caller, the depths each key takes by its kind
# and the broadest of them the caller could hand out at their own workspace:
# `platform.holder_covers_grant`, the hold rule's own comparison (step 5).
_PERMISSIONS = sa.text(
    """
    SELECT p.key, p.area, p.label_vi, p.scope_kind, p.risk, p.status, d.allowed_depths,
           (SELECT x.depth
            FROM unnest(d.allowed_depths) WITH ORDINALITY x(depth, n)
            WHERE platform.holder_covers_grant(
                CAST(:t AS uuid), CAST(:u AS uuid), p.key, x.depth, CAST(:w AS uuid))
            ORDER BY x.n DESC LIMIT 1) AS max_grantable_depth
    FROM platform.permissions p
    CROSS JOIN LATERAL (
        SELECT CASE p.scope_kind
                   WHEN 'tenant' THEN ARRAY['tenant']
                   WHEN 'workspace' THEN ARRAY['workspace', 'tenant']
                   ELSE ARRAY['own', 'workspace', 'tenant']
               END AS allowed_depths
    ) d
    ORDER BY p.area, p.key
    """
)


@dataclass(frozen=True)
class SqlAdminConsoleRepository:
    """Implements ``AdminConsoleRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_workspaces(self, context: AccessContext) -> list[WorkspaceSummary]:
        member_count = (
            sa.select(sa.func.count())
            .select_from(tables.memberships)
            .where(tables.memberships.c.workspace_id == tables.workspaces.c.id)
            .scalar_subquery()
        )
        query = (
            sa.select(
                tables.workspaces.c.id,
                tables.workspaces.c.slug,
                tables.workspaces.c.name,
                tables.workspaces.c.archived_at,
                member_count.label("member_count"),
            )
            .where(tables.workspaces.c.tenant_id == context.tenant_id)
            .order_by(tables.workspaces.c.name)
        )
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            rows = (await session.execute(query)).all()
        return [
            WorkspaceSummary(
                workspace_id=row.id,
                slug=row.slug,
                name=row.name,
                member_count=row.member_count,
                archived=row.archived_at is not None,
            )
            for row in rows
        ]

    async def create_workspace(
        self,
        context: AccessContext,
        *,
        workspace_id: uuid.UUID,
        slug: str,
        name: str,
        audit: AuditEvent,
    ) -> WorkspaceRef:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            try:
                await session.execute(
                    sa.insert(tables.workspaces).values(
                        id=workspace_id,
                        tenant_id=context.tenant_id,
                        slug=slug,
                        name=name,
                    )
                )
            except IntegrityError as exc:
                if _WORKSPACE_SLUG_CONSTRAINT in str(exc.orig):
                    raise ConflictError(
                        "a workspace with that slug already exists in this tenant",
                        details={"slug": slug},
                    ) from exc
                raise
            await SqlAuditRepository(session).append(audit)
        return WorkspaceRef(workspace_id=workspace_id, slug=slug, name=name)

    async def rename_workspace(
        self, context: AccessContext, *, workspace_id: uuid.UUID, name: str, audit: AuditEvent
    ) -> WorkspaceRef | None:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            row = (
                await session.execute(
                    sa.update(tables.workspaces)
                    .where(
                        tables.workspaces.c.id == workspace_id,
                        tables.workspaces.c.tenant_id == context.tenant_id,
                    )
                    .values(name=name)
                    .returning(tables.workspaces.c.slug)
                )
            ).first()
            if row is None:
                return None
            await SqlAuditRepository(session).append(audit)
        return WorkspaceRef(workspace_id=workspace_id, slug=row.slug, name=name)

    async def archive_workspace(
        self, context: AccessContext, *, workspace_id: uuid.UUID, audit: AuditEvent
    ) -> bool:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            row = (
                await session.execute(
                    sa.update(tables.workspaces)
                    .where(
                        tables.workspaces.c.id == workspace_id,
                        tables.workspaces.c.tenant_id == context.tenant_id,
                        tables.workspaces.c.archived_at.is_(None),
                    )
                    .values(archived_at=sa.func.now())
                    .returning(tables.workspaces.c.id)
                )
            ).first()
            if row is None:
                return False
            await SqlAuditRepository(session).append(audit)
        return True

    async def list_permission_sets(self) -> list[PermissionSetInfo]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(
                        tables.permission_sets.c.key,
                        tables.permission_sets.c.name,
                        tables.permission_sets.c.scopes,
                    ).order_by(tables.permission_sets.c.key)
                )
            ).all()
        return [
            PermissionSetInfo(key=row.key, name=row.name, scopes=tuple(row.scopes)) for row in rows
        ]

    async def list_permissions(self, context: AccessContext) -> list[PermissionInfo]:
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            rows = (
                await session.execute(
                    _PERMISSIONS,
                    {
                        "t": str(context.tenant_id),
                        "u": str(context.principal_id),
                        "w": str(context.workspace_id),
                    },
                )
            ).all()
        return [
            PermissionInfo(
                key=row.key,
                area=row.area,
                label_vi=row.label_vi,
                scope_kind=row.scope_kind,
                risk=row.risk,
                status=row.status,
                allowed_depths=tuple(row.allowed_depths),
                max_grantable_depth=row.max_grantable_depth,
            )
            for row in rows
        ]

    async def get_tenant_settings(self, context: AccessContext) -> TenantSettings | None:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            row = (
                await session.execute(
                    sa.select(
                        tables.tenants.c.id,
                        tables.tenants.c.slug,
                        tables.tenants.c.name,
                        tables.tenants.c.status,
                        tables.tenants.c.record_visibility,
                        tables.tenants.c.max_autonomy_level,
                        tables.tenants.c.timezone,
                        tables.tenants.c.locale,
                    ).where(tables.tenants.c.id == context.tenant_id)
                )
            ).first()
        if row is None:
            return None
        return _to_settings(row)

    async def update_tenant_settings(
        self, context: AccessContext, *, command: UpdateTenantSettings, audit: AuditEvent
    ) -> TenantSettings | None:
        values: dict[str, object] = {}
        if command.name is not None:
            values["name"] = command.name
        if command.timezone is not None:
            values["timezone"] = command.timezone
        if command.locale is not None:
            values["locale"] = command.locale
        if command.record_visibility is not None:
            values["record_visibility"] = command.record_visibility
        if command.max_autonomy_level is not None:
            values["max_autonomy_level"] = command.max_autonomy_level
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            if values:
                row = (
                    await session.execute(
                        sa.update(tables.tenants)
                        .where(tables.tenants.c.id == context.tenant_id)
                        .values(**values)
                        .returning(
                            tables.tenants.c.id,
                            tables.tenants.c.slug,
                            tables.tenants.c.name,
                            tables.tenants.c.status,
                            tables.tenants.c.record_visibility,
                            tables.tenants.c.max_autonomy_level,
                            tables.tenants.c.timezone,
                            tables.tenants.c.locale,
                        )
                    )
                ).first()
            else:
                row = (
                    await session.execute(
                        sa.select(
                            tables.tenants.c.id,
                            tables.tenants.c.slug,
                            tables.tenants.c.name,
                            tables.tenants.c.status,
                            tables.tenants.c.record_visibility,
                            tables.tenants.c.max_autonomy_level,
                            tables.tenants.c.timezone,
                            tables.tenants.c.locale,
                        ).where(tables.tenants.c.id == context.tenant_id)
                    )
                ).first()
            if row is None:
                return None
            if values:
                await SqlAuditRepository(session).append(audit)
        return _to_settings(row)


def _to_settings(row: sa.Row) -> TenantSettings:  # type: ignore[type-arg]
    return TenantSettings(
        tenant_id=row.id,
        slug=row.slug,
        name=row.name,
        status=row.status,
        record_visibility=row.record_visibility,
        timezone=row.timezone,
        locale=row.locale,
        max_autonomy_level=row.max_autonomy_level,
    )
