"""Promote a signed-in user to Platform Admin + Org Admin of a tenant.

The first-admin bootstrap. Default-deny means nobody can grant the very first
admin through the app, so this maintenance script does it directly, as the
migrator role (BYPASSRLS) — the same trust level as the seed.

The person must have signed in once first (SSO creates their identity with no
membership); this attaches the admin roles to that identity, found by email.
Idempotent: re-running updates the roles rather than duplicating the membership.

    DW_DATABASE_URL=postgresql+asyncpg://dw_migrator:...@host/dw \
        uv run python scripts/grant_platform_admin.py --email datpt142@fpt.com
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.tenant_member_rows import ensure_tenant_member

ADMIN_ROLES = ["platform_admin", "org_admin"]


async def _run(database_url: str, email: str, tenant_slug: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            user = (
                await conn.execute(
                    sa.select(tables.users.c.id, tables.users.c.display_name).where(
                        sa.func.lower(tables.users.c.email) == email.strip().lower()
                    )
                )
            ).first()
            if user is None:
                print(
                    f"No user with email {email!r} has signed in yet. "
                    "Ask them to log in once, then re-run this.",
                    file=sys.stderr,
                )
                return 1

            tenant = (
                await conn.execute(
                    sa.select(tables.tenants.c.id, tables.tenants.c.name).where(
                        tables.tenants.c.slug == tenant_slug
                    )
                )
            ).first()
            if tenant is None:
                print(f"No tenant with slug {tenant_slug!r}. Run the seed first.", file=sys.stderr)
                return 1

            workspace = (
                await conn.execute(
                    sa.select(tables.workspaces.c.id).where(
                        tables.workspaces.c.tenant_id == tenant.id,
                        tables.workspaces.c.slug == "main",
                    )
                )
            ).first()
            if workspace is None:
                print(f"Tenant {tenant_slug!r} has no 'main' workspace.", file=sys.stderr)
                return 1

            # An operator's command for a person who has signed in: an `active`
            # member of the company; a row already there keeps its status.
            await conn.execute(ensure_tenant_member(tenant.id, user.id, "active"))
            stmt = pg_insert(tables.memberships).values(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                user_id=user.id,
                role_keys=ADMIN_ROLES,
                department="admin",
            )
            await conn.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_memberships_scope_user",
                    set_={"role_keys": ADMIN_ROLES},
                )
            )
        print(
            f"Granted {ADMIN_ROLES} to {user.display_name} <{email}> "
            f"in tenant {tenant.name!r} (workspace 'main')."
        )
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="datpt142@fpt.com", help="the user's email")
    parser.add_argument("--tenant-slug", default="tenant-alpha", help="tenant to admin (FDX)")
    args = parser.parse_args()

    database_url = os.environ.get("DW_DATABASE_URL")
    if not database_url:
        print("DW_DATABASE_URL is required (the migrator connection).", file=sys.stderr)
        return 1
    return asyncio.run(_run(database_url, args.email, args.tenant_slug))


if __name__ == "__main__":
    raise SystemExit(main())
