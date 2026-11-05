"""`dw_studio`'s table description against the migrated catalog (studio-skeleton R6.7).

Alembic's `compare_metadata` over schema `studio` after `alembic upgrade head`:
tables, columns, types, nullability, server defaults, keys and indexes.

What it cannot see, measured on PostgreSQL 16 with alembic's autogenerate
(3/11/2026), each planted and rolled back, each reported as no difference:

- the predicate of a partial index (`uq_artifact_versions_unreleased` narrowed
  to `stage = 'draft'`);
- a CHECK constraint (`ck_artifacts_api_name` dropped);
- a row-level security policy (`tenant_isolation_artifacts` dropped);
- a column grant (`UPDATE (labels)` revoked from `dw_app`);
- a trigger (`refuse_api_name_change` dropped).

Those are held elsewhere: the policies by `test_rls_coverage.py`, the grants by
`test_privileges.py`, the CHECKs, triggers and the partial index by the
behaviour tests of `test_artifact_envelope.py`. It does see an index's column
order and direction and a key's `ON DELETE`, measured the same way.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pg_test_db import DatabaseUrls
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import dw_studio.records.adapters.tables  # noqa: F401 - its tables join `metadata`
from dw_studio.core.adapters.tables import metadata

pytestmark = pytest.mark.integration


# The `platform` tables this package describes (tenant-config ticket 04).
_PLATFORM_TABLES = frozenset(
    table.name for table in metadata.tables.values() if table.schema == "platform"
)


# The partitions of `studio.records` are the migration's alone: rows are read
# through the parent (custom-objects ticket 02), and `test_rls_coverage.py`
# holds each partition's policy to the parent's.
_PARTITION = re.compile(r"^records_p[0-9]+$")


def _studio_only(name: str | None, type_: str, parent: dict[str, Any]) -> bool:
    if type_ == "schema":
        return name in {"studio", "platform"}
    if type_ == "table":
        schema = parent.get("schema_name")
        if schema == "studio":
            return not _PARTITION.match(name or "")
        return schema == "platform" and name in _PLATFORM_TABLES
    return True


def _not_into_a_partition(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """A foreign key to the partitioned `studio.records` (`record_write_keys`,
    custom-objects ticket 03) is one constraint in the description and, in the
    catalog, one more per partition that PostgreSQL makes and names itself."""
    if type_ == "foreign_key_constraint" and reflected:
        return not _PARTITION.match(obj.referred_table.name)
    return True


def _differences(conn: Connection) -> list[Any]:
    context = MigrationContext.configure(
        conn,
        opts={
            "include_schemas": True,
            "include_name": _studio_only,
            "include_object": _not_into_a_partition,
            "compare_type": True,
            "compare_server_default": True,
        },
    )
    return list(compare_metadata(context, metadata))


async def _differences_after(studio_db: DatabaseUrls, *statements: str) -> list[Any]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            tx = await conn.begin()
            for statement in statements:
                await conn.execute(sa.text(statement))
            found = await conn.run_sync(_differences)
            await tx.rollback()
    finally:
        await engine.dispose()
    return found


async def test_the_description_matches_the_migrated_catalog(studio_db: DatabaseUrls) -> None:
    assert await _differences_after(studio_db) == []
    assert {t.name for t in metadata.tables.values()} >= {
        "artifact_kinds",
        "artifacts",
        "artifact_versions",
        "definition_manifests",
        "dependencies",
        "run_manifests",
        "run_manifest_keys",
        "object_defs",
        "field_defs",
        "picklist_options",
        "records",
    }


async def test_a_column_a_migration_adds_and_the_description_lacks_is_named(
    studio_db: DatabaseUrls,
) -> None:
    found = await _differences_after(
        studio_db, "ALTER TABLE studio.artifacts ADD COLUMN probe_column text"
    )
    assert [(d[0], d[1], d[2], d[3].name) for d in found] == [
        ("remove_column", "studio", "artifacts", "probe_column")
    ]


async def test_an_index_in_another_order_is_named(studio_db: DatabaseUrls) -> None:
    found = await _differences_after(
        studio_db,
        "DROP INDEX studio.ix_artifacts_tenant_id_updated_at_id",
        "CREATE INDEX ix_artifacts_tenant_id_updated_at_id"
        " ON studio.artifacts (tenant_id, updated_at, id)",
    )
    assert sorted(d[0] for d in found) == ["add_index", "remove_index"]
