"""The registry the running app uses, against the database (tenant-config R2.15).

`PLATFORM_KINDS`, which `build_studio` registers when no test passes `kinds=`,
names exactly the kinds of `studio.artifact_kinds`; every key of every entry
is in the one permission catalogue, active; every entry carries a publish
hook. Both sets are empty until a kind's spec registers one, so each check is
also run with one defect planted and must name it (failure-modes #3).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

import pytest
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from dw_studio.core.application.registry import PLATFORM_KINDS, ArtifactKindEntry
from dw_studio.testing.fixture_kinds import FIXTURE, FIXTURE_KINDS, planted_fixture_kinds

pytestmark = pytest.mark.integration


async def registry_problems(
    conn: AsyncConnection, entries: Sequence[ArtifactKindEntry]
) -> list[str]:
    rows = {r.kind for r in await conn.execute(sa.text("SELECT kind FROM studio.artifact_kinds"))}
    active = {
        r.key
        for r in await conn.execute(
            sa.text("SELECT key FROM platform.permissions WHERE status = 'active'")
        )
    }
    registered = {entry.kind for entry in entries}
    found = [f"kind {k} has a row and no registry entry" for k in sorted(rows - registered)]
    found += [f"kind {k} is registered and has no row" for k in sorted(registered - rows)]
    for entry in entries:
        found += [
            f"kind {entry.kind}: key {key} is not an active key of the catalogue"
            for key in entry.keys
            if key not in active
        ]
        hook: object = entry.publish_hook
        if not callable(hook):
            found.append(f"kind {entry.kind} has no publish hook")
    return found


async def test_the_running_registry_is_the_kind_table(studio_db: DatabaseUrls) -> None:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            assert await registry_problems(conn, PLATFORM_KINDS) == []
            await conn.rollback()
            # A row with no entry, and an entry with no row: each named.
            tx = await conn.begin()
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifact_kinds (kind, has_quality_gate)"
                    " VALUES ('probe_kind', true)"
                )
            )
            row_only = await registry_problems(conn, PLATFORM_KINDS)
            await tx.rollback()
            entry_only = await registry_problems(conn, (*PLATFORM_KINDS, FIXTURE))
    finally:
        await engine.dispose()

    assert row_only == ["kind probe_kind has a row and no registry entry"]
    assert "kind fixture is registered and has no row" in entry_only


async def test_a_kind_without_a_catalogued_key_or_a_hook_is_named(studio_db: DatabaseUrls) -> None:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    try:
        async with planted_fixture_kinds(engine), engine.connect() as conn:
            assert await registry_problems(conn, FIXTURE_KINDS) == []
            unread = dataclasses.replace(FIXTURE, read_key="fixture.artifacts.unknown")
            hookless = dataclasses.replace(FIXTURE, publish_hook=_none())
            found = await registry_problems(conn, (unread,))
            found += await registry_problems(conn, (hookless,))
            await conn.rollback()
    finally:
        await engine.dispose()

    assert found == [
        "kind fixture_gateless has a row and no registry entry",
        "kind fixture: key fixture.artifacts.unknown is not an active key of the catalogue",
        "kind fixture_gateless has a row and no registry entry",
        "kind fixture has no publish hook",
    ]


def _none() -> Any:
    return None


async def test_nothing_of_the_fixture_kinds_outlives_their_block(studio_db: DatabaseUrls) -> None:
    """R2.15: after a module that used them, no row of either kind or its keys."""
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            left = await conn.scalar(
                sa.text(
                    "SELECT (SELECT count(*) FROM studio.artifact_kinds"
                    "        WHERE kind IN ('fixture', 'fixture_gateless'))"
                    " + (SELECT count(*) FROM platform.permissions WHERE key LIKE 'fixture.%')"
                    " + (SELECT count(*) FROM studio.artifacts"
                    "    WHERE kind IN ('fixture', 'fixture_gateless'))"
                )
            )
    finally:
        await engine.dispose()
    assert left == 0
