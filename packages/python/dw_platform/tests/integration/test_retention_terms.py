"""Integration: the retention fragment set and its runtime copy (spec R5.6, R5.9-R5.13).

The fragments are the terms; `platform.retention_terms` is what a purge
function that takes no argument reads them from. Every test here asks the
running database, because that is where both the copy and the names a fragment
may carry live (`failure-modes.md` #0).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url, provisioner_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from studio_catalog import append_only_violations

from dw_platform.adapters.persistence import retention_terms
from dw_platform.adapters.persistence.partition_maintenance import AUDIT_EVENTS
from dw_platform.adapters.persistence.retention_terms import (
    loaded_terms,
    pinned_terms,
    retention_term_drift,
    sync_retention_terms,
)
from dw_platform.retention_policy import (
    NAMED_STORES,
    RetentionFragment,
    RetentionPolicy,
    load_retention_policy,
)

pytestmark = pytest.mark.integration

PINNED = load_retention_policy()


def _fragment(days: int | str | None, *, enforced: bool = True) -> RetentionFragment:
    purger = "none" if days == "indefinite" else "row_delete"
    return RetentionFragment.model_validate(
        {"days": days, "purger": purger, "enforced": enforced, "description": "thử"}
    )


def _with(stores: Mapping[str, RetentionFragment]) -> RetentionPolicy:
    return PINNED.model_copy(update={"stores": dict(stores)})


@pytest.fixture
async def engine_as(db_urls: DatabaseUrls) -> AsyncIterator[dict[str, AsyncEngine]]:
    engines = {
        "admin": create_async_engine(admin_url(db_urls), poolclass=NullPool),
        "app": create_async_engine(db_urls.app, poolclass=NullPool),
        "provisioner": create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool),
    }
    try:
        yield engines
    finally:
        for engine in engines.values():
            await engine.dispose()


# --------------------------------------------------------------------- R5.6 --
async def fragment_name_violations(
    conn: AsyncConnection, keys: set[str], named_stores: frozenset[str]
) -> list[str]:
    """Each fragment key that is neither `<schema>.<table>` of a table nor a named store."""
    found = []
    for key in sorted(keys - named_stores):
        exists = await conn.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n"
                " ON n.oid = c.relnamespace WHERE c.relkind IN ('r', 'p')"
                " AND n.nspname || '.' || c.relname = :key)"
            ),
            {"key": key},
        )
        if not exists:
            found.append(f"R5.6 fragment {key}.yaml names no table and no named store")
    return found


async def test_every_pinned_fragment_names_a_table_or_a_named_store(
    engine_as: dict[str, AsyncEngine],
) -> None:
    async with engine_as["admin"].connect() as conn:
        assert await fragment_name_violations(conn, set(PINNED.stores), NAMED_STORES) == []


async def test_a_fragment_named_for_nothing_is_named_and_a_named_store_is_accepted(
    engine_as: dict[str, AsyncEngine],
) -> None:
    keys = {AUDIT_EVENTS, "platform.no_such_table", "objects.probe_payloads"}
    async with engine_as["admin"].connect() as conn:
        found = await fragment_name_violations(conn, keys, frozenset({"objects.probe_payloads"}))
    assert found == ["R5.6 fragment platform.no_such_table.yaml names no table and no named store"]


# -------------------------------------------------------------------- R5.13 --
async def test_without_its_fragment_the_audit_log_fails_the_registry_term_check(
    engine_as: dict[str, AsyncEngine],
) -> None:
    """studio-skeleton R3.7 on the fragment reader: no fragment, no term, red
    naming the table. Under the provisional mapping to `retention@1.7.0` the
    table still had a term here, and this passed."""
    without = _with({k: v for k, v in PINNED.stores.items() if k != AUDIT_EVENTS})
    async with engine_as["admin"].connect() as conn:
        assert [v for v in await append_only_violations(conn, PINNED.term) if "R3.7" in v] == []
        found = await append_only_violations(conn, without.term)
    assert any(v.startswith(f"R3.7 {AUDIT_EVENTS} ") for v in found), found


# --------------------------------------------------------------- R5.9, R5.10 --
async def test_the_loader_makes_the_table_exactly_the_fragment_set(
    engine_as: dict[str, AsyncEngine],
) -> None:
    """Set A, then set B with one term changed, one fragment gone, one added,
    one decided but not enforced and one that never expires: the table is B's
    enforced numbers and nothing else."""
    a = _with({"t.kept": _fragment(30), "t.gone": _fragment(60), "t.changed": _fragment(90)})
    b = _with(
        {
            "t.kept": _fragment(30),
            "t.changed": _fragment(45),
            "t.added": _fragment(10),
            "t.not_yet": _fragment(20, enforced=False),
            "t.forever": _fragment("indefinite"),
        }
    )
    async with engine_as["provisioner"].connect() as conn:
        await sync_retention_terms(conn, a)
        assert await loaded_terms(conn) == {"t.kept": 30, "t.gone": 60, "t.changed": 90}
        await sync_retention_terms(conn, b)
        loaded = await loaded_terms(conn)
        await conn.rollback()
    assert loaded == {"t.kept": 30, "t.changed": 45, "t.added": 10} == pinned_terms(b)


async def test_the_deployed_table_matches_the_pinned_fragment_set(
    engine_as: dict[str, AsyncEngine],
) -> None:
    """The fixture migrated and then ran the loader, as the `migrate` job does."""
    async with engine_as["app"].connect() as conn:
        loaded = await loaded_terms(conn)
    assert retention_term_drift(loaded, pinned_terms(PINNED)) == []
    assert loaded[AUDIT_EVENTS] == 1095


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        (
            "UPDATE platform.retention_terms SET term_days = 1"
            " WHERE store_key = 'platform.audit_events'",
            "platform.audit_events holds 1 days, the fragment says 1095",
        ),
        (
            "INSERT INTO platform.retention_terms VALUES ('platform.extra', 5)",
            "platform.extra not in the pinned fragment set",
        ),
        (
            "DELETE FROM platform.retention_terms WHERE store_key = 'platform.audit_events'",
            "platform.audit_events missing",
        ),
    ],
    ids=["changed", "extra", "missing"],
)
async def test_a_drifted_table_is_named_by_key(
    engine_as: dict[str, AsyncEngine], statement: str, expected: str
) -> None:
    async with engine_as["admin"].connect() as conn:
        await conn.execute(sa.text(statement))
        found = retention_term_drift(await loaded_terms(conn), pinned_terms(PINNED))
        await conn.rollback()
    assert found == [expected]


def _table(db_urls: DatabaseUrls) -> dict[str, int]:
    async def read() -> dict[str, int]:
        engine = create_async_engine(db_urls.app, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return await loaded_terms(conn)
        finally:
            await engine.dispose()

    return asyncio.run(read())


def test_the_loader_exits_non_zero_and_changes_nothing_when_it_cannot_load(
    monkeypatch: pytest.MonkeyPatch, db_urls: DatabaseUrls
) -> None:
    before = _table(db_urls)
    monkeypatch.delenv("DW_PROVISIONER_DATABASE_URL", raising=False)
    assert retention_terms.main() == 2

    def broken() -> RetentionPolicy:
        raise ValueError("platform.audit_events.yaml: broken")

    monkeypatch.setenv("DW_PROVISIONER_DATABASE_URL", provisioner_url(db_urls.migrator))
    monkeypatch.setattr(retention_terms, "load_retention_policy", broken)
    assert retention_terms.main() == 1

    monkeypatch.undo()
    monkeypatch.setenv(
        "DW_PROVISIONER_DATABASE_URL", "postgresql+asyncpg://dw_provisioner:x@127.0.0.1:1/dw"
    )
    assert retention_terms.main() == 1
    assert _table(db_urls) == before


# -------------------------------------------------------------------- R5.12 --
async def test_a_term_nobody_loaded_raises_instead_of_answering(
    engine_as: dict[str, AsyncEngine],
) -> None:
    async with engine_as["admin"].connect() as conn:
        assert (
            await conn.scalar(sa.text(f"SELECT platform.retention_term_days('{AUDIT_EVENTS}')"))
            == 1095
        )
        with pytest.raises(
            Exception, match=r"no retention term is loaded for platform\.nope"
        ) as raised:
            await conn.execute(sa.text("SELECT platform.retention_term_days('platform.nope')"))
        await conn.rollback()
    assert getattr(raised.value.orig, "sqlstate", None) == "P0002"  # type: ignore[attr-defined]


async def test_no_role_may_call_the_term_reader(engine_as: dict[str, AsyncEngine]) -> None:
    """Only the narrow purge functions, owned by the migrator, call it."""
    async with engine_as["admin"].connect() as conn:
        callers = (
            await conn.execute(
                sa.text(
                    "SELECT r.rolname FROM pg_roles r"
                    " WHERE r.rolname IN ('dw_app', 'dw_provisioner', 'dw_agent_ro')"
                    " AND has_function_privilege(r.rolname,"
                    " 'platform.retention_term_days(text)', 'EXECUTE')"
                )
            )
        ).all()
    assert callers == []
