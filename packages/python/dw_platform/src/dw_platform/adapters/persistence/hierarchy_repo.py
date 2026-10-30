"""SQL implementation of the reporting hierarchy (ADR-003).

Everything runs through ``tenant_session`` so RLS bounds it to the caller's
tenant, and each query also pins ``tenant_id`` and ``workspace_id`` explicitly.
The subtree walk is a recursive CTE — ``root`` plus everyone whose
``manager_user_id`` chains back to it, inside the one tenant + workspace.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.repositories import SqlAuditRepository
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.hierarchy import HierarchyMember
from dw_platform.domain.audit import AuditEvent

SUBTREE_QUERY = text(
    """
    WITH RECURSIVE sub AS (
        SELECT user_id FROM platform.memberships
        WHERE tenant_id = :tenant AND workspace_id = :ws AND user_id = :root
      UNION
        SELECT m.user_id FROM platform.memberships m
        JOIN sub ON m.manager_user_id = sub.user_id
        WHERE m.tenant_id = :tenant AND m.workspace_id = :ws
    )
    SELECT user_id FROM sub
    """
)


@dataclass(frozen=True)
class SqlHierarchyRepository:
    """Implements ``HierarchyRepositoryPort`` and the resolver's data access."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_members(self, context: AccessContext) -> list[HierarchyMember]:
        query = (
            sa.select(
                tables.memberships.c.user_id,
                tables.memberships.c.role_keys,
                tables.memberships.c.manager_user_id,
                tables.users.c.display_name,
                tables.users.c.email,
            )
            .select_from(
                tables.memberships.join(
                    tables.users, tables.memberships.c.user_id == tables.users.c.id
                )
            )
            .where(
                tables.memberships.c.tenant_id == context.tenant_id,
                tables.memberships.c.workspace_id == context.workspace_id,
                tables.HUMAN,
            )
            .order_by(tables.users.c.display_name)
        )
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            rows = (await session.execute(query)).all()
        return [
            HierarchyMember(
                user_id=row.user_id,
                display_name=row.display_name,
                email=row.email,
                role_keys=tuple(row.role_keys),
                manager_user_id=row.manager_user_id,
            )
            for row in rows
        ]

    async def is_member(self, context: AccessContext, user_id: uuid.UUID) -> bool:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            found = (
                await session.execute(
                    sa.select(tables.memberships.c.id).where(
                        tables.memberships.c.tenant_id == context.tenant_id,
                        tables.memberships.c.workspace_id == context.workspace_id,
                        tables.memberships.c.user_id == user_id,
                    )
                )
            ).first()
        return found is not None

    async def subtree_user_ids(
        self, context: AccessContext, root_user_id: uuid.UUID
    ) -> frozenset[uuid.UUID]:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            rows = (
                await session.execute(
                    SUBTREE_QUERY,
                    {
                        "tenant": str(context.tenant_id),
                        "ws": str(context.workspace_id),
                        "root": str(root_user_id),
                    },
                )
            ).all()
        return frozenset(row.user_id for row in rows)

    async def set_manager(
        self,
        context: AccessContext,
        *,
        user_id: uuid.UUID,
        manager_user_id: uuid.UUID | None,
        audit: AuditEvent,
    ) -> bool:
        scope = TenantScope.from_access_context(context)
        async with tenant_session(self.session_factory, scope) as session:
            row = (
                await session.execute(
                    sa.update(tables.memberships)
                    .where(
                        tables.memberships.c.tenant_id == context.tenant_id,
                        tables.memberships.c.workspace_id == context.workspace_id,
                        tables.memberships.c.user_id == user_id,
                    )
                    .values(manager_user_id=manager_user_id)
                    .returning(tables.memberships.c.id)
                )
            ).first()
            if row is None:
                return False
            await SqlAuditRepository(session).append(audit)
        return True
