"""Planting tenant roles and assignments for a test, in raw SQL.

A fixture that needs a person holding a key writes the rows the way the
platform holds them since migration b5677d345bc1: a tenant (its system roles
installed, as provisioning does), workspaces, company members, memberships,
tenant roles with their privileges, and role assignments. Run it on a
connection that may write every tenant (the migrator), or one bound to the
tenant. The keys a role carries must be in `platform.permissions`; a test key
is registered with `register_key` and removed with `unregister_key`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from dw_platform.testing.members import MemberStatus, add_tenant_member

Conn = AsyncConnection | AsyncSession


@dataclass(frozen=True)
class PlantedTenant:
    tenant_id: uuid.UUID
    workspaces: tuple[uuid.UUID, ...]

    @property
    def main(self) -> uuid.UUID:
        return self.workspaces[0]


async def _run(conn: Conn, statement: str, values: Mapping[str, object] | None = None) -> None:
    await conn.execute(sa.text(statement), dict(values or {}))


async def plant_tenant(
    conn: Conn, *, status: str = "active", workspaces: int = 1, plan_id: str = "professional"
) -> PlantedTenant:
    """A tenant with `workspaces` workspaces (the first is `main`), a plan and
    its system roles."""
    tenant = PlantedTenant(uuid.uuid4(), tuple(uuid.uuid4() for _ in range(workspaces)))
    await _run(
        conn,
        "INSERT INTO platform.tenants (id, slug, name, status) VALUES (:t, :slug, :slug, :s)",
        {"t": tenant.tenant_id, "slug": f"rbac-{tenant.tenant_id.hex[:12]}", "s": status},
    )
    for n, ws in enumerate(tenant.workspaces):
        await _run(
            conn,
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name) VALUES (:w, :t, :s, :s)",
            {"w": ws, "t": tenant.tenant_id, "s": "main" if n == 0 else f"ws{n}"},
        )
    await _run(
        conn,
        "INSERT INTO platform.entitlements (id, tenant_id, plan_id) VALUES (:id, :t, :p)",
        {"id": uuid.uuid4(), "t": tenant.tenant_id, "p": plan_id},
    )
    await _run(conn, "SELECT platform.install_system_roles(:t)", {"t": tenant.tenant_id})
    return tenant


async def plant_person(
    conn: Conn,
    tenant_id: uuid.UUID,
    *,
    status: MemberStatus = "active",
    kind: str = "human",
    email: str | None = None,
) -> uuid.UUID:
    """A user and their company row in `tenant_id`."""
    user = uuid.uuid4()
    await _run(
        conn,
        "INSERT INTO platform.users (id, subject, email, display_name, kind, owner_tenant_id)"
        " VALUES (:u, :s, :e, 'Người thử', :k, :o)",
        {
            "u": user,
            "s": f"rbac-{user}",
            "e": email,
            "k": kind,
            "o": tenant_id if kind == "service" else None,
        },
    )
    await add_tenant_member(conn, tenant_id, user, status)
    return user


async def plant_membership(
    conn: Conn, tenant_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID:
    """A membership with empty legacy columns; its roles come from `assign`."""
    membership = uuid.uuid4()
    await _run(
        conn,
        "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
        " VALUES (:m, :t, :w, :u)",
        {"m": membership, "t": tenant_id, "w": workspace_id, "u": user_id},
    )
    return membership


async def plant_role(
    conn: Conn,
    tenant_id: uuid.UUID,
    key: str,
    privileges: Mapping[str, str],
    *,
    kind: str = "role",
) -> uuid.UUID:
    """A tenant role carrying `privileges` (key -> depth)."""
    role = uuid.uuid4()
    await _run(
        conn,
        "INSERT INTO platform.tenant_roles (id, tenant_id, key, name, kind)"
        " VALUES (:r, :t, :k, :k, :kind)",
        {"r": role, "t": tenant_id, "k": key, "kind": kind},
    )
    for permission, depth in privileges.items():
        await grant_privilege(conn, tenant_id, role, permission, depth)
    return role


async def grant_privilege(
    conn: Conn, tenant_id: uuid.UUID, role_id: uuid.UUID, key: str, depth: str
) -> None:
    await _run(
        conn,
        "INSERT INTO platform.tenant_role_permissions (tenant_id, role_id, permission_key, depth)"
        " VALUES (:t, :r, :k, :d)",
        {"t": tenant_id, "r": role_id, "k": key, "d": depth},
    )


async def assign(
    conn: Conn,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    expires_at: datetime | None = None,
    assigned_at: datetime | None = None,
) -> uuid.UUID:
    assignment = uuid.uuid4()
    await _run(
        conn,
        "INSERT INTO platform.role_assignments"
        " (id, tenant_id, workspace_id, membership_id, role_id, expires_at, assigned_at)"
        " VALUES (:a, :t, :w, :m, :r, :x, coalesce(CAST(:at AS timestamptz), now()))",
        {
            "a": assignment,
            "t": tenant_id,
            "w": workspace_id,
            "m": membership_id,
            "r": role_id,
            "x": expires_at,
            "at": assigned_at,
        },
    )
    return assignment


async def role_id(conn: Conn, tenant_id: uuid.UUID, key: str) -> uuid.UUID:
    found = await conn.scalar(
        sa.text("SELECT id FROM platform.tenant_roles WHERE tenant_id = :t AND key = :k"),
        {"t": tenant_id, "k": key},
    )
    assert found is not None, f"tenant {tenant_id} has no role {key}"
    return uuid.UUID(str(found))


async def register_key(
    conn: Conn,
    key: str,
    *,
    scope_kind: str = "workspace",
    status: str = "active",
    tenant_grantable: bool = True,
) -> None:
    """A catalogue row for a test key, every NOT NULL column named. Migrator only."""
    await _run(
        conn,
        "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
        " status_reason, owner_package, tenant_grantable)"
        " VALUES (:k, 'test', 'Khóa thử', :kind, 'standard', :s,"
        " CASE WHEN :s = 'active' THEN NULL ELSE 'khóa thử' END, 'tests', :g)",
        {"k": key, "kind": scope_kind, "s": status, "g": tenant_grantable},
    )


async def unregister_key(conn: Conn, key: str) -> None:
    """Remove a test key and every privilege naming it. Migrator only."""
    await _run(
        conn, "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k", {"k": key}
    )
    await _run(conn, "DELETE FROM platform.permissions WHERE key = :k", {"k": key})


async def grants_of(conn: Conn, tenant_id: uuid.UUID, user_id: uuid.UUID) -> set[tuple[str, str]]:
    """`platform.effective_grants` as (key, depth) pairs."""
    rows = await conn.execute(
        sa.text("SELECT permission_key, depth FROM platform.effective_grants(:t, :u)"),
        {"t": tenant_id, "u": user_id},
    )
    return {(r.permission_key, r.depth) for r in rows}


async def scopes_in(
    conn: Conn, tenant_id: uuid.UUID, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> set[str]:
    rows = await conn.execute(
        sa.text("SELECT platform.scopes_in(:t, :u, :w) AS k"),
        {"t": tenant_id, "u": user_id, "w": workspace_id},
    )
    return {r.k for r in rows}


async def catalogue_test_keys(conn: Conn, keys: object) -> None:
    """Put a fixture's made-up keys in the catalogue before a template names them.

    Since migration b5677d345bc1 a tenant role's privilege is a foreign key into
    `platform.permissions`, so a template (`platform.roles`, `platform.permission_sets`)
    that grants a key the catalogue lacks cannot be cloned into a tenant. A key
    already there is left as it is. `retired`, with its reason: no code checks a
    test's key, which is what `test_permission_catalogue.py` asks of an active
    one. Migrator only.
    """
    for key in keys if not isinstance(keys, str) else [keys]:  # type: ignore[attr-defined]
        await _run(
            conn,
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " status_reason, owner_package, tenant_grantable)"
            " VALUES (:k, 'test', 'Khóa của một test', 'workspace', 'standard', 'retired',"
            " 'khóa của một test, không code nào kiểm', 'tests', true)"
            " ON CONFLICT (key) DO NOTHING",
            {"k": key},
        )
