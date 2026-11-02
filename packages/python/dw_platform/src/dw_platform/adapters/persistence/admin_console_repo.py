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
from dw_platform.adapters.persistence.separation_of_duties import (
    separation_of_duties_conflict,
)
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.admin_console import (
    PermissionInfo,
    PermissionSetInfo,
    RoleInfo,
    TenantSettings,
    UpdateTenantSettings,
    WorkspaceRef,
    WorkspaceSummary,
)
from dw_platform.domain.audit import AuditEvent

_WORKSPACE_SLUG_CONSTRAINT = "uq_workspaces_tenant_slug"


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

    async def list_roles(self) -> list[RoleInfo]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(
                        tables.roles.c.key, tables.roles.c.name, tables.roles.c.scopes
                    ).order_by(tables.roles.c.key)
                )
            ).all()
        return [RoleInfo(key=row.key, name=row.name, scopes=tuple(row.scopes)) for row in rows]

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

    async def list_permissions(self) -> list[PermissionInfo]:
        p = tables.permissions
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(
                        p.c.key, p.c.area, p.c.label_vi, p.c.scope_kind, p.c.risk, p.c.status
                    ).order_by(p.c.area, p.c.key)
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
            )
            for row in rows
        ]

    async def known_permission_sets(self, keys: frozenset[str]) -> frozenset[str]:
        if not keys:
            return frozenset()
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(tables.permission_sets.c.key).where(
                        tables.permission_sets.c.key.in_(keys)
                    )
                )
            ).all()
        return frozenset(row.key for row in rows)

    async def scopes_for_permission_sets(self, keys: frozenset[str]) -> frozenset[str]:
        if not keys:
            return frozenset()
        scopes: set[str] = set()
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(tables.permission_sets.c.scopes).where(
                        tables.permission_sets.c.key.in_(keys)
                    )
                )
            ).all()
        for (set_scopes,) in rows:
            scopes.update(set_scopes)
        return frozenset(scopes)

    async def set_permission_sets(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        permission_set_keys: frozenset[str],
        audit: AuditEvent,
    ) -> bool:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            try:
                row = (
                    await session.execute(
                        sa.update(tables.memberships)
                        .where(
                            tables.memberships.c.tenant_id == context.tenant_id,
                            tables.memberships.c.workspace_id == context.workspace_id,
                            tables.memberships.c.user_id == user_id,
                        )
                        .values(permission_set_keys=sorted(permission_set_keys))
                        .returning(tables.memberships.c.id)
                    )
                ).first()
            except IntegrityError as exc:
                # A permission set cannot carry a scope past separation of
                # duties either: the trigger judges roles and sets together.
                conflict = separation_of_duties_conflict(exc)
                if conflict is None:
                    raise
                raise conflict from exc
            if row is None:
                return False
            await SqlAuditRepository(session).append(audit)
        return True

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
