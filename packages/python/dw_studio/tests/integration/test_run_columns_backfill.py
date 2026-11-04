"""Revision 703be798341f on a database that already holds runs (workflow-engine
ticket 02, R3.1): every existing row becomes its own root, at depth 0, and
keeps the `updated_at` it had (a running row is aged by it).

Its own database, migrated to the revision before, seeded as the migrator,
then upgraded.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_test_db import database_urls, recreate_database, run_alembic
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.rbac import plant_tenant

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

TEST_DB = "dw_test_run_columns_backfill"
BEFORE, REVISION = "9b97696ff72f", "703be798341f"
TOUCHED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


async def test_the_revision_makes_every_existing_run_its_own_root() -> None:
    urls = database_urls(TEST_DB)
    await recreate_database(urls.admin, TEST_DB)
    migrated = await asyncio.to_thread(run_alembic, ["upgrade", BEFORE], urls.migrator)
    assert migrated.returncode == 0, migrated.stderr

    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    runs = [uuid.uuid4(), uuid.uuid4()]
    try:
        async with engine.begin() as conn:
            tenant = await plant_tenant(conn)
            for run_id, status in zip(runs, ("running", "completed"), strict=True):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.worker_runs (id, thread_id, tenant_id, workspace_id,"
                        " worker_id, worker_version, graph_version, status, requested_by,"
                        " run_mode, created_at, updated_at)"
                        " VALUES (:r, :r, :t, :w, 'code_worker', '1', '1', :s,"
                        " gen_random_uuid(), 'live', :at, :at)"
                    ),
                    {
                        "r": run_id,
                        "t": tenant.tenant_id,
                        "w": tenant.main,
                        "s": status,
                        "at": TOUCHED,
                    },
                )
        upgraded = await asyncio.to_thread(run_alembic, ["upgrade", REVISION], urls.migrator)
        assert upgraded.returncode == 0, upgraded.stderr
        async with engine.connect() as conn:
            found = {
                row.id: row
                for row in await conn.execute(
                    sa.text(
                        "SELECT id, root_run_id, chain_depth, priority, attempt, updated_at"
                        " FROM platform.worker_runs WHERE id = ANY(:r)"
                    ),
                    {"r": runs},
                )
            }
    finally:
        await engine.dispose()
    for run_id in runs:
        row = found[run_id]
        assert (row.root_run_id, row.chain_depth) == (run_id, 0)
        assert (row.priority, row.attempt) == (0, 0)
        assert row.updated_at == TOUCHED
