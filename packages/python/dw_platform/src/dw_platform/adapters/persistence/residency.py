"""The tenant's and the workspace's data route class, read under RLS
(compliance-pdpl R2.1, R2.2; ADR-0123 decision 3).

`read_route_classes` is the one read of the two columns: the gate's
`SqlRouteClasses` asks it on its own transaction for a call outside a run, and
each admission door asks it inside the transaction that writes the run row, so
the class a run pins and the class a request is checked against come from one
query. It decides nothing; `dw_kernel.residency.effective_route_class` does.

A row the session cannot read raises: a workspace of another tenant is a row
RLS does not return, and the gate refuses on it (failure-modes #7).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.errors import NotFoundError
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session

__all__ = ["SqlRouteClasses", "read_route_classes"]

_ROUTE_CLASSES = sa.text(
    "SELECT t.data_route_class AS tenant_class, w.data_route_class AS workspace_class,"
    " w.id IS NOT NULL AS workspace_found"
    " FROM platform.tenants t"
    " LEFT JOIN platform.workspaces w ON w.tenant_id = t.id AND w.id = CAST(:w AS uuid)"
    " WHERE t.id = CAST(:t AS uuid)"
)


async def read_route_classes(
    session: AsyncSession, tenant_id: uuid.UUID, workspace_id: uuid.UUID | None
) -> tuple[str, str | None]:
    """`(tenant class, workspace class)` on a session already bound to `tenant_id`."""
    row = (
        await session.execute(
            _ROUTE_CLASSES,
            {"t": str(tenant_id), "w": None if workspace_id is None else str(workspace_id)},
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("the tenant's data route class cannot be read")
    if workspace_id is not None and not row.workspace_found:
        raise NotFoundError("the workspace's data route class cannot be read")
    return row.tenant_class, row.workspace_class


@dataclass(frozen=True)
class SqlRouteClasses:
    """`dw_kernel.residency.RouteClassReader` on the application role."""

    session_factory: async_sessionmaker[AsyncSession]

    async def route_classes(
        self, tenant_id: uuid.UUID, workspace_id: uuid.UUID | None
    ) -> tuple[str, str | None]:
        scope = TenantScope(tenant_id=tenant_id, workspace_id=workspace_id)
        async with tenant_session(self.session_factory, scope) as session:
            return await read_route_classes(session, tenant_id, workspace_id)
