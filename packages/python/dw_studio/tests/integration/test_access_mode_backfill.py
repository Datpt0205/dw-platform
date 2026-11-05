"""Revision 2f177d264a27 on a database that already holds field definitions
(field-security ticket 01, R1.7; FS15): every personal-data field is
`secured`, a field without personal data `open`, each row keeps the
`updated_at` it had, and the sensitive CHECK is in place; then the downgrade
takes the column, its two CHECKs and its two triggers away, the table staying.

Its own database, migrated to the revision before, seeded as the migrator,
then upgraded and downgraded.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pg_test_db import database_urls, recreate_database, run_alembic
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.rbac import plant_tenant
from dw_platform.testing.record_objects import plant_object

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

TEST_DB = "dw_test_access_mode_backfill"
BEFORE, REVISION = "996c234cfde3", "2f177d264a27"
TOUCHED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

_CATALOG = sa.text(
    "SELECT (SELECT array_agg(conname::text ORDER BY conname) FROM pg_constraint"
    "        WHERE conrelid = 'studio.field_defs'::regclass"
    "          AND conname IN ('ck_field_defs_access_mode', 'ck_field_defs_sensitive_is_secured'))"
    "       AS checks,"
    "       (SELECT array_agg(tgname::text ORDER BY tgname) FROM pg_trigger"
    "        WHERE tgrelid = 'studio.field_defs'::regclass"
    "          AND tgname IN ('trg_field_defs_secure_personal_data',"
    "                         'trg_z_bump_access_version_access_mode')) AS triggers,"
    "       EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'studio'"
    "               AND table_name = 'field_defs' AND column_name = 'access_mode') AS column"
)


async def _alembic(*args: str, url: str) -> None:
    done = await asyncio.to_thread(run_alembic, list(args), url)
    assert done.returncode == 0, done.stderr


async def _catalog(engine: AsyncEngine) -> sa.Row[tuple[object, ...]]:
    async with engine.connect() as conn:
        return (await conn.execute(_CATALOG)).one()


async def test_r1_7_fs15_existing_personal_data_fields_become_secured() -> None:
    urls = database_urls(TEST_DB)
    await recreate_database(urls.admin, TEST_DB)
    await _alembic("upgrade", BEFORE, url=urls.migrator)

    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            tenant = await plant_tenant(conn)
            lead = await plant_object(
                conn, tenant, "lead", {"phone": "basic", "cccd": "sensitive", "note": "none"}
            )
            await conn.execute(
                sa.text("UPDATE studio.field_defs SET updated_at = :at WHERE object_id = :o"),
                {"at": TOUCHED, "o": lead.object_id},
            )

        await _alembic("upgrade", REVISION, url=urls.migrator)

        async with engine.connect() as conn:
            found = {
                r.api_name: (r.access_mode, r.updated_at)
                for r in await conn.execute(
                    sa.text(
                        "SELECT api_name, access_mode, updated_at FROM studio.field_defs"
                        " WHERE object_id = :o"
                    ),
                    {"o": lead.object_id},
                )
            }
        assert found == {
            "phone": ("secured", TOUCHED),
            "cccd": ("secured", TOUCHED),
            "note": ("open", TOUCHED),
        }
        catalog = await _catalog(engine)
        assert catalog.checks == [
            "ck_field_defs_access_mode",
            "ck_field_defs_sensitive_is_secured",
        ]
        assert catalog.triggers == [
            "trg_field_defs_secure_personal_data",
            "trg_z_bump_access_version_access_mode",
        ]

        await _alembic("downgrade", BEFORE, url=urls.migrator)

        catalog = await _catalog(engine)
        assert (catalog.checks, catalog.triggers, catalog.column) == (None, None, False)
        async with engine.connect() as conn:
            kept = await conn.scalar(
                sa.text("SELECT count(*) FROM studio.field_defs WHERE object_id = :o"),
                {"o": lead.object_id},
            )
            function = await conn.scalar(
                sa.text("SELECT to_regprocedure('studio.secure_personal_field()') IS NULL")
            )
        assert (kept, function) == (3, True)
    finally:
        await engine.dispose()
