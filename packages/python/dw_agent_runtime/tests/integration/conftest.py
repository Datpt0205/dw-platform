"""Fixture: migrated runtime test database (fails loudly without infra)."""

from __future__ import annotations

import asyncio

import pytest
from runtime_harness import (
    TENANT_A,
    TENANT_B,
    TEST_DB,
    WORKSPACE_A,
    WORKSPACE_B,
    RuntimeUrls,
    recreate_database,
    run_migrations,
    runtime_urls,
)
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture(scope="session")
def urls() -> RuntimeUrls:
    resolved = runtime_urls()
    try:
        asyncio.run(recreate_database(resolved.admin, TEST_DB))
    except (OSError, OperationalError, InterfaceError) as exc:
        pytest.fail(f"Postgres unreachable — run `make infra-up` first. Error: {exc}")
    result = run_migrations(resolved.migrator)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")
    asyncio.run(_seed_tenants(resolved.migrator))
    return resolved


async def _seed_tenants(migrator_url: str) -> None:
    """The two tenants `make_run_context` names, each with its workspace.

    A table with a foreign key to its tenant and workspace (a tool claim,
    runtime-hardening R6.8) refuses rows for a tenant that does not exist, so
    the harness creates the ones its contexts point at.
    """
    engine = create_async_engine(migrator_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            for tenant, workspace, slug in (
                (TENANT_A, WORKSPACE_A, "runtime-a"),
                (TENANT_B, WORKSPACE_B, "runtime-b"),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO platform.tenants (id, slug, name) VALUES (:id, :slug, :slug)"
                        " ON CONFLICT DO NOTHING"
                    ),
                    {"id": tenant, "slug": slug},
                )
                await conn.execute(
                    text(
                        "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                        " VALUES (:id, :tenant, 'main', 'main') ON CONFLICT DO NOTHING"
                    ),
                    {"id": workspace, "tenant": tenant},
                )
    finally:
        await engine.dispose()
