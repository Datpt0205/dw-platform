"""`SqlLiveScopes`: what a run's principal holds now in the run's workspace
(workflow-engine R6.12), the runtime's `LiveScopesPort`.

The answer is the database's, `platform.scopes_in` through `effective_scopes`,
the projection the access context, `/me` and the scope holders read too
(tenant-rbac R2.2, ADR-0104 decision 5): nothing here decides which key
counts. A principal that is no longer an active member of the company gets
None, and the run waits instead of going on with the scopes it began with.
One short transaction under the run's tenant; never cached, so a grant revoked
while the run waited is gone at its next take.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.membership_lookup import effective_scopes
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session


@dataclass(frozen=True)
class SqlLiveScopes:
    session_factory: async_sessionmaker[AsyncSession]

    async def scopes(
        self, tenant_id: UUID, workspace_id: UUID, principal_id: UUID
    ) -> frozenset[str] | None:
        async with tenant_session(
            self.session_factory, TenantScope(tenant_id=tenant_id)
        ) as session:
            status = await session.scalar(
                sa.select(tables.tenant_members.c.status).where(
                    tables.tenant_members.c.tenant_id == tenant_id,
                    tables.tenant_members.c.user_id == principal_id,
                )
            )
            if status != "active":
                return None
            return await effective_scopes(session, tenant_id, principal_id, workspace_id)
