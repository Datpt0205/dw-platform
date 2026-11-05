"""Records for a test, and a test's connection bound as a Studio request
(record-access ticket 03) or as a run's actor (ticket 04).

`act_as_user` binds a raw connection the way `user_session` binds a request's
session: tenant and principal, the actor kind `user`, then the reach door. It
is one of the allowed callers of `bind_actor` (`test_session_setting_scan.py`),
so a test reads under the policies exactly as the API door would make it.
`act_as_run` binds a raw connection the way the runtime's tool session binds an
agent's call, or the workflow runner a workflow's: tenant and the run's
principal, the run's actor from its row, then the reach door.
`plant_record` writes a record past the reach policies, in the caller's
transaction, bound to the record's tenant because the owner check reads it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from dw_platform.adapters.persistence.tenant_session import TenantScope, bind_actor, bind_tenant

_DOOR = sa.text("SELECT studio.ensure_principal_scope()")
_BIND_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_INSERT = sa.text(
    "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind, owner_id,"
    " name, created_at, created_by, updated_by, deleted_at)"
    " VALUES (:id, :t, :o, :w, 'user', :owner, :name, coalesce(CAST(:at AS timestamptz), now()),"
    " :owner, :owner, :deleted)"
)


async def act_as_user(conn: AsyncConnection, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Bind ``conn``'s open transaction as ``user_id``'s request in ``tenant_id``."""
    await bind_tenant(conn, TenantScope(tenant_id=tenant_id, principal_id=user_id))
    await bind_actor(conn, "user")
    (await conn.execute(_DOOR)).first()


async def act_as_run(
    conn: AsyncConnection | AsyncSession,
    tenant_id: uuid.UUID,
    principal_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    kind: Literal["agent", "workflow"] = "agent",
    workspace_id: uuid.UUID | None = None,
) -> None:
    """Bind ``conn``'s open transaction as run ``run_id``'s ``kind`` acting as
    ``principal_id`` in ``tenant_id`` (and ``workspace_id``, the run's, where
    a new record goes)."""
    await bind_tenant(
        conn,
        TenantScope(tenant_id=tenant_id, workspace_id=workspace_id, principal_id=principal_id),
    )
    if kind == "agent":
        await bind_actor(conn, "agent", run_id=run_id)
    else:
        await bind_actor(conn, "workflow", run_id=run_id)
    (await conn.execute(_DOOR)).first()


async def plant_record(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    object_id: uuid.UUID,
    workspace_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    name: str = "Bản ghi thử",
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> uuid.UUID:
    """One record, as the caller's role (the migrator, past the reach policies),
    owned by ``owner_id``, who must be an active member of ``tenant_id``."""
    record = uuid.uuid4()
    await conn.execute(_BIND_TENANT, {"t": str(tenant_id)})
    await conn.execute(
        _INSERT,
        {
            "id": record,
            "t": tenant_id,
            "o": object_id,
            "w": workspace_id,
            "owner": owner_id,
            "name": name,
            "at": created_at,
            "deleted": deleted_at,
        },
    )
    return record
