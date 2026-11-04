"""`SqlRunBindings`: `RunBindingsPort` over a run's row and its pinned manifest
(tenant-config ticket 05 step 9, R7.5; ADR-0109 decision 6; V4.35).

One short transaction bound to the asking tenant (RLS): another tenant's run
is no run. The connection comes from the `bindings` section of the run's own
manifest, never from the Binding set approved now, so a new set approved while
the run waits changes nothing; the principal from the run row,
`coalesce(run_as_principal_id, requested_by)`, since the manifest names none
(gate 4/11/2026 (m)).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import worker_runs
from dw_agent_runtime.ports import BoundConnection
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_studio.core.adapters.tables import run_manifests
from dw_studio.core.domain.bindings import as_uuid


@dataclass(frozen=True)
class SqlRunBindings:
    session_factory: async_sessionmaker[AsyncSession]

    async def connection(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, binding_name: str
    ) -> BoundConnection | None:
        async with tenant_session(self.session_factory, TenantScope(tenant_id=tenant_id)) as s:
            row = (
                await s.execute(
                    sa.select(
                        worker_runs.c.workspace_id,
                        worker_runs.c.created_at,
                        sa.func.coalesce(
                            worker_runs.c.run_as_principal_id, worker_runs.c.requested_by
                        ).label("principal_id"),
                        run_manifests.c.body,
                    )
                    .select_from(
                        worker_runs.join(
                            run_manifests,
                            sa.and_(
                                run_manifests.c.tenant_id == worker_runs.c.tenant_id,
                                run_manifests.c.hash == worker_runs.c.run_manifest_hash,
                            ),
                        )
                    )
                    .where(worker_runs.c.id == run_id)
                )
            ).first()
        if row is None or row.principal_id is None:
            return None
        values = ((row.body or {}).get("bindings") or {}).get("values") or {}
        pinned = values.get(binding_name)
        if not isinstance(pinned, dict) or pinned.get("kind") != "connection":
            return None
        connection_id = as_uuid(pinned.get("connection_id"))
        if connection_id is None:
            return None
        return BoundConnection(
            connection_id=connection_id,
            workspace_id=row.workspace_id,
            principal_id=row.principal_id,
            run_requested_at=row.created_at,
        )
