"""Revision 6503c6f309b1 on a database that already holds versions
(agent-lifecycle ticket 03, step 1): `contributor_ids` backfilled from the
`studio.artifact.*` audit of each row's artifact, first appearance first, and
a row no such audit names stops the revision, naming it, instead of being
given an arbitrary person.

Its own database, migrated to the revision before, seeded as the migrator,
then upgraded.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pg_test_db import database_urls, recreate_database, run_alembic
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.testing.rbac import plant_tenant

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

TEST_DB = "dw_test_lifecycle_backfill"
BEFORE, REVISION = "8efd60e59d32", "6503c6f309b1"
HASH = "sha256:" + "b" * 64


async def _artifact(conn: AsyncConnection, tenant: uuid.UUID, ws: uuid.UUID) -> uuid.UUID:
    artifact_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
            " row_version) VALUES (:a, :t, 'object', :n, :w, 1)"
        ),
        {"a": artifact_id, "t": tenant, "n": f"a_{artifact_id.hex[:12]}", "w": ws},
    )
    return artifact_id


async def _version(
    conn: AsyncConnection, tenant: uuid.UUID, artifact_id: uuid.UUID, *, stage: str, number: int
) -> uuid.UUID:
    version_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage, version_no,"
            " document_schema, document, content_hash, definition_hash, row_version)"
            " VALUES (:v, :t, :a, :s, :n, 'dw.object/v1', '{}', :h, :h, 1)"
        ),
        {"v": version_id, "t": tenant, "a": artifact_id, "s": stage, "n": number, "h": HASH},
    )
    return version_id


async def _audit(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    ws: uuid.UUID,
    artifact_id: uuid.UUID,
    actor: uuid.UUID,
    action: str,
    at: datetime,
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO platform.audit_events (id, tenant_id, workspace_id, actor_id, action,"
            " resource_type, resource_id, occurred_at)"
            " VALUES (:id, :t, :w, :u, :x, 'studio_artifact', :r, :at)"
        ),
        {
            "id": uuid.uuid4(),
            "t": tenant,
            "w": ws,
            "u": actor,
            "x": action,
            "r": str(artifact_id),
            "at": at,
        },
    )


async def test_the_revision_backfills_contributors_and_stops_on_a_row_without_audit() -> None:
    urls = database_urls(TEST_DB)
    await recreate_database(urls.admin, TEST_DB)
    migrated = await asyncio.to_thread(run_alembic, ["upgrade", BEFORE], urls.migrator)
    assert migrated.returncode == 0, migrated.stderr
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    start = datetime(2026, 11, 1, tzinfo=UTC)
    try:
        async with engine.begin() as conn:
            tenant = await plant_tenant(conn)
            orphan_tenant = await plant_tenant(conn)
            ws = tenant.main
            named = await _artifact(conn, tenant.tenant_id, ws)
            # A live v1 and a draft v2 of one artifact (stages from before the
            # machine): both name everyone the artifact's audit names.
            v1 = await _version(conn, tenant.tenant_id, named, stage="live", number=1)
            v2 = await _version(conn, tenant.tenant_id, named, stage="draft", number=2)
            for actor, action, minutes in (
                (b, "studio.artifact.draft_saved", 5),
                (a, "studio.artifact.created", 0),
                (b, "studio.artifact.draft_saved", 9),
                (c, "studio.version.submitted", 7),  # not studio.artifact.*
            ):
                await _audit(
                    conn,
                    tenant.tenant_id,
                    ws,
                    named,
                    actor,
                    action,
                    start + timedelta(minutes=minutes),
                )
            orphan = await _artifact(conn, orphan_tenant.tenant_id, orphan_tenant.main)
            orphan_v = await _version(
                conn, orphan_tenant.tenant_id, orphan, stage="draft", number=1
            )

        refused = await asyncio.to_thread(run_alembic, ["upgrade", REVISION], urls.migrator)
        assert refused.returncode != 0
        assert str(orphan_v) in refused.stderr and "ck_artifact_versions_contributor_ids" in (
            refused.stderr
        )
        async with engine.connect() as conn:
            assert await conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == BEFORE

        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
                {"t": orphan_tenant.tenant_id},
            )
            await conn.execute(
                sa.text("DELETE FROM studio.artifact_versions WHERE id = :v"), {"v": orphan_v}
            )
        upgraded = await asyncio.to_thread(run_alembic, ["upgrade", REVISION], urls.migrator)
        assert upgraded.returncode == 0, upgraded.stderr

        async with engine.connect() as conn:
            found = {
                row.id: row.contributor_ids
                for row in await conn.execute(
                    sa.text("SELECT id, contributor_ids FROM studio.artifact_versions")
                )
            }
        assert found == {v1: [a, b], v2: [a, b]}
    finally:
        await engine.dispose()
