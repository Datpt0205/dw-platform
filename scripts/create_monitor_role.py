"""Create the monitoring login role ``dw_monitor``. Idempotent, admin-only.

runtime-hardening R8.4. ``postgres-exporter`` reads statistics, so it connects
as a role that holds ``pg_monitor`` and nothing else: no table grant, no
BYPASSRLS, no CREATE. It used to connect as ``dw_app``, whose password opens
every tenant's rows under RLS; a leaked exporter credential now opens none.

A role is a cluster object and ``dw_migrator`` has no CREATEROLE, so a migration
cannot make it. Fresh clusters get it from
``infra/compose/init/init-databases.sh``; this script is for a cluster that was
initialised before the role existed, and the integration test creates it with
this script too, so the two cannot drift.

Usage:
    uv run python scripts/create_monitor_role.py
    uv run python scripts/create_monitor_role.py --admin-url postgresql+asyncpg://...
"""

from __future__ import annotations

import argparse
import asyncio
import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROLE = "dw_monitor"
DATABASE = "dw"
# What the role is, in the one place both creation paths read it from.
ATTRIBUTES = "LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"


def _admin_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    url = os.environ.get("DW_ADMIN_DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("DW_DB_HOST", "127.0.0.1")
    port = os.environ.get("DW_DB_PORT", "5432")
    if not user or not password:
        raise SystemExit(
            "Set DW_ADMIN_DATABASE_URL, or POSTGRES_USER and POSTGRES_PASSWORD, "
            "or pass --admin-url. Creating a role needs an account with CREATEROLE."
        )
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/postgres"


def _password(explicit: str | None = None) -> str:
    password = explicit or os.environ.get("DW_DB_MONITOR_PASSWORD")
    if not password:
        raise SystemExit(
            "DW_DB_MONITOR_PASSWORD is not set. Add it to .env with the value "
            "postgres-exporter's DATA_SOURCE_NAME uses; an empty one is refused."
        )
    if "\\" in password:
        raise SystemExit("DW_DB_MONITOR_PASSWORD contains a backslash; pick one without.")
    return password


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def create_monitor_role(admin_url: str, password: str, *, database: str = DATABASE) -> str:
    """Create or update the role; 'created' or 'updated'."""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                sa.text("SELECT true FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
            )
            verb = "ALTER" if exists else "CREATE"
            await conn.execute(
                sa.text(f"{verb} ROLE {ROLE} {ATTRIBUTES} PASSWORD {_literal(password)}")
            )
            await conn.execute(sa.text(f"GRANT pg_monitor TO {ROLE}"))
            # Back to what is declared, on a cluster where someone granted more.
            extra = (
                await conn.execute(
                    sa.text(
                        "SELECT b.rolname FROM pg_auth_members m"
                        " JOIN pg_roles b ON b.oid = m.roleid"
                        " JOIN pg_roles r ON r.oid = m.member"
                        " WHERE r.rolname = :r AND b.rolname <> 'pg_monitor'"
                    ),
                    {"r": ROLE},
                )
            ).scalars()
            for granted in extra:
                await conn.execute(sa.text(f'REVOKE "{granted}" FROM {ROLE}'))
            if await conn.scalar(
                sa.text("SELECT true FROM pg_database WHERE datname = :d"), {"d": database}
            ):
                await conn.execute(sa.text(f'GRANT CONNECT ON DATABASE "{database}" TO {ROLE}'))
            return "updated" if exists else "created"
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--admin-url", help="a URL for an account with CREATEROLE")
    args = parser.parse_args()
    outcome = asyncio.run(create_monitor_role(_admin_url(args.admin_url), _password()))
    print(f"{ROLE}: {outcome}")


if __name__ == "__main__":
    main()
