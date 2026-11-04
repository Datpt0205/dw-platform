"""SQL side of the tenant-wide member list.

Runs as `dw_app` under the caller's tenant (`tenant_session`): RLS on
`platform.memberships` and `platform.workspaces` bounds every read to that
tenant, and the query names the tenant again. `platform.users` is the identity
plane (no tenant column), so every read of it hangs off a membership of this
tenant. A membership's roles are its assignments (`held_role_keys`), never the
legacy `role_keys` column (tenant-rbac ticket 03); placing people in roles is
`role_assignments_repo.py`'s.

Names sort with the ICU Vietnamese collation (`vi-VN-x-icu`), present in the
pinned `postgres:16-alpine` image (measured 2026-10-08: Đ after D, Ê after E;
the database default puts every accented name after Z). The list is not paged:
it is one tenant's people, read through `ix_memberships_tenant_user`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.directory import held_role_keys, member_status
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.tenant_members import MemberWorkspace, TenantMember

VIETNAMESE = "vi-VN-x-icu"
_M = tables.memberships


@dataclass(frozen=True)
class SqlTenantMembersRepository:
    """Implements ``TenantMembersRepositoryPort``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_members(self, context: AccessContext) -> list[TenantMember]:
        query = (
            sa.select(
                tables.users.c.id,
                tables.users.c.display_name,
                tables.users.c.email,
                member_status().label("status"),
                _M.c.workspace_id,
                tables.workspaces.c.name.label("workspace_name"),
                held_role_keys("role").label("role_keys"),
            )
            .select_from(
                _M.join(tables.users, tables.users.c.id == _M.c.user_id).join(
                    tables.workspaces, tables.workspaces.c.id == _M.c.workspace_id
                )
            )
            .where(_M.c.tenant_id == context.tenant_id, tables.HUMAN)
            .order_by(
                tables.users.c.display_name.collate(VIETNAMESE),
                tables.users.c.id,
                tables.workspaces.c.name.collate(VIETNAMESE),
                _M.c.workspace_id,
            )
        )
        async with tenant_session(self.session_factory, _scope(context)) as session:
            rows = (await session.execute(query)).all()
        members: dict[uuid.UUID, TenantMember] = {}
        for row in rows:
            entry = MemberWorkspace(
                workspace_id=row.workspace_id,
                workspace_name=row.workspace_name,
                role_keys=tuple(sorted(row.role_keys)),
            )
            known = members.get(row.id)
            members[row.id] = TenantMember(
                user_id=row.id,
                display_name=row.display_name,
                email=row.email,
                status=row.status,
                memberships=((*known.memberships, entry) if known else (entry,)),
            )
        return list(members.values())


def _scope(context: AccessContext) -> TenantScope:
    return TenantScope.from_access_context(context)
