"""Which named workspaces are the caller's company's, for the audience validator.

The tenant is named in the statement and not left to RLS alone:
`workspaces_self_select` lets a connection whose `app.principal_id` is set see
every workspace that person has a membership in, another tenant's included, so
a filter by policy only would accept tenant B's workspace in tenant A's audience
on such a connection. One statement per document.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext


class SqlAudienceWorkspaces:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def known(self, context: AccessContext, ids: frozenset[UUID]) -> frozenset[UUID]:
        if not ids:
            return frozenset()
        workspaces = tables.workspaces
        statement = sa.select(workspaces.c.id).where(
            workspaces.c.tenant_id == context.tenant_id,
            workspaces.c.id.in_(sorted(ids)),
        )
        async with tenant_session(self._sessions, TenantScope.from_access_context(context)) as s:
            return frozenset((await s.scalars(statement)).all())
