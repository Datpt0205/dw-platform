"""Offboarding reaches every tenant table of `studio` and every new tenant table
of `platform` (studio-skeleton R4).

The offboarding lane exports then purges what the catalog says `dw_app` may
SELECT and DELETE. A table it may only read by column, or may not delete from,
is skipped without a word, and that tenant's rows outlive the tenant. So every
such table is either handled or listed, with how it loses its rows, and the
listing is checked against the running catalog both ways:

- the export and the purge are judged apart, because being deleted another way
  says nothing about being handed back to the customer first;
- a purge exclusion names one way: the table it cascades from, the function
  that deletes it, or the retention fragment that keeps it for a term;
- every RESTRICT and NO ACTION edge the catalog holds (never a copied list,
  failure-modes #0) runs the way the adapter deletes, read from the one function
  `purge_rows` walks;
- the `platform` tables that predate the rule are listed once, and the list can
  only shrink: a table created after this ticket's migration has a larger OID.

Every check runs on the migrated checkout, then on defects planted in a
transaction that rolls back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.offboarding import (
    _CATALOG_EXPORTABLE,
    _NEVER_PURGE,
    EXPORT_EXCLUSIONS,
    STUDIO_EXCLUSIONS,
    OffboardingExclusion,
    SqlTenantOffboarding,
)
from dw_platform.retention_policy import RetentionPolicy, RetentionTerm, load_retention_policy

pytestmark = pytest.mark.integration

# The tenant tables of `platform` when this rule arrived (studio-skeleton
# ticket 01, 27/10/2026), measured from the catalog: offboarding's coverage of
# them is foundations-hardening's, not this test's. The list only shrinks; a
# table made after `platform.time_partitioned_tables` cannot join it (R4.6).
_PLATFORM_PREDATING: dict[str, str] = dict.fromkeys(
    (
        "platform.agent_store",
        "platform.approval_decision_codes",
        "platform.approval_decisions",
        "platform.approval_requests",
        "platform.approval_view_receipts",
        "platform.audit_events",
        "platform.channel_deliveries",
        "platform.channel_preferences",
        "platform.entitlements",
        "platform.feedback",
        "platform.feedback_attachments",
        "platform.idempotency_keys",
        "platform.memberships",
        "platform.notifications",
        "platform.outbox_events",
        "platform.policy_overrides",
        "platform.run_checkpoint_writes",
        "platform.run_checkpoints",
        "platform.sod_waivers",
        "platform.support_grants",
        "platform.tenant_daily_spend_guard",
        "platform.tenant_offboarding_requests",
        "platform.tool_executions",
        "platform.worker_runs",
        "platform.workspaces",
    ),
    "có trước luật, 27/10/2026",
)

_TENANT_TABLES = sa.text(
    """
    SELECT n.nspname || '.' || c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('studio', 'platform') AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'tenant_id' AND NOT a.attisdropped)
    """
)

_FOREIGN_KEYS = sa.text(
    """
    SELECT k.conname, k.confdeltype::text,
           an.nspname || '.' || a.relname AS referencing,
           bn.nspname || '.' || b.relname AS referenced
    FROM pg_constraint k
    JOIN pg_class a ON a.oid = k.conrelid JOIN pg_namespace an ON an.oid = a.relnamespace
    JOIN pg_class b ON b.oid = k.confrelid JOIN pg_namespace bn ON bn.oid = b.relnamespace
    WHERE k.contype = 'f' AND NOT a.relispartition
    """
)

_FUNCTIONS = sa.text(
    "SELECT n.nspname || '.' || p.proname FROM pg_proc p"
    " JOIN pg_namespace n ON n.oid = p.pronamespace"
)

_LATER_THAN_THE_REGISTRY = sa.text(
    """
    SELECT n.nspname || '.' || c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname || '.' || c.relname = ANY(:names)
      AND c.oid > 'platform.time_partitioned_tables'::regclass::oid
    """
)

TermOf = Callable[[str], RetentionTerm | None]


async def offboarding_violations(
    conn: AsyncConnection,
    purge_exclusions: Mapping[str, OffboardingExclusion],
    export_exclusions: Mapping[str, str],
    predating: Mapping[str, str],
    term_of: TermOf,
) -> list[str]:
    """R4.1-R4.6, one line per defect."""
    async with AsyncSession(bind=conn) as session:
        order = await SqlTenantOffboarding(session_factory=None).purge_order(session)  # type: ignore[arg-type]
    position = {step: at for at, step in enumerate(order)}
    tables = set((await conn.execute(_TENANT_TABLES)).scalars().all())
    never = {f"{schema}.{table}" for schema, table in _NEVER_PURGE}
    exported = {
        f"{row.schemaname}.{row.tablename}"
        for row in (await conn.execute(_CATALOG_EXPORTABLE)).all()
    } - never
    functions = set((await conn.execute(_FUNCTIONS)).scalars().all())
    edges = (await conn.execute(_FOREIGN_KEYS)).all()
    found: list[str] = []

    # R4.1, R4.3: each side handled, or listed.
    for table in sorted(tables):
        if table in predating:
            continue
        rule = "R4.1" if table.startswith("studio.") else "R4.3"
        if table not in exported and table not in export_exclusions:
            found.append(f"{rule} {table} is not exported and has no export exclusion")
        if table not in position and table not in purge_exclusions:
            found.append(f"{rule} {table} is not purged and has no purge exclusion")

    # R4.4: every purge exclusion is the way the catalog says it is.
    def deleted_at(table: str) -> int | None:
        if table in position:
            return position[table]
        way = purge_exclusions.get(table)
        if way is None:
            return None
        if way.cascade_from is not None:
            return position.get(way.cascade_from)
        if way.function is not None:
            return position.get(way.function)
        return None

    for table, way in sorted(purge_exclusions.items()):
        if way.cascade_from is not None:
            cascades = any(
                e.referencing == table and e.referenced == way.cascade_from and e.confdeltype == "c"
                for e in edges
            )
            if not cascades or way.cascade_from not in position:
                found.append(
                    f"R4.4 {table}: no ON DELETE CASCADE to {way.cascade_from}"
                    " that the lane deletes"
                )
        if way.function is not None and (
            way.function not in functions or way.function not in position
        ):
            found.append(f"R4.4 {table}: {way.function} is not a deleting step of the lane")
        if way.kept is not None:
            term = term_of(way.kept)
            if way.kept != table or term is None or not term.enforced:
                found.append(f"R4.4 {table}: kept without an enforced term of its own")
            for e in edges:
                if (
                    e.referencing == table
                    and e.confdeltype in ("c", "n", "d")
                    and deleted_at(e.referenced) is not None
                ):
                    found.append(
                        f"R4.4 {table}: kept, yet {e.conname} rewrites it from {e.referenced}"
                    )
    found += [
        f"R4.4 export exclusion {table} has no reason"
        for table, reason in sorted(export_exclusions.items())
        if not reason.strip()
    ]

    # R4.5: rows for tables gone or already handled.
    for table in sorted(purge_exclusions):
        if table not in tables:
            found.append(f"R4.5 purge exclusion {table} names no table")
        elif table in position:
            found.append(f"R4.5 purge exclusion {table} names a table the lane purges")
    for table in sorted(export_exclusions):
        if table not in tables:
            found.append(f"R4.5 export exclusion {table} names no table")
        elif table in exported:
            found.append(f"R4.5 export exclusion {table} names a table the lane exports")
    found += [
        f"R4.5 predating {table} names no table"
        for table in sorted(predating)
        if table not in tables
    ]

    # R4.6: the predating list only shrinks.
    later = await conn.execute(_LATER_THAN_THE_REGISTRY, {"names": sorted(predating)})
    found += [f"R4.6 {name} postdates the rule" for name in sorted(later.scalars().all())]

    # R4.2: an edge that blocks a delete runs the lane's way.
    for e in edges:
        if e.confdeltype not in ("r", "a"):
            continue
        if not (e.referencing.startswith("studio.") or e.referenced.startswith("studio.")):
            continue
        if e.referenced not in tables or e.referencing not in tables:
            continue
        referenced = deleted_at(e.referenced)
        if referenced is None:
            continue
        referencing = deleted_at(e.referencing)
        if referencing is None or referencing >= referenced:
            found.append(
                f"R4.2 {e.conname}: {e.referenced} is deleted before {e.referencing} references it"
            )
    return found


def _pinned_policy() -> RetentionPolicy:
    return load_retention_policy()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_offboarding_covers_every_table_it_has_to(migrator: AsyncEngine) -> None:
    """R4.1-R4.6 on the migrated checkout."""
    policy = _pinned_policy()
    async with migrator.connect() as conn:
        found = await offboarding_violations(
            conn,
            STUDIO_EXCLUSIONS,
            EXPORT_EXCLUSIONS,
            _PLATFORM_PREDATING,
            policy.term,
        )
    assert found == []


_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _table(name: str, *, columns: str = "", purgeable: bool = True) -> list[str]:
    """A tenant table the lane can see: a `tenant_isolation_*` policy and, when
    `purgeable`, SELECT and DELETE for dw_app; otherwise SELECT of one column."""
    short = name.split(".", 1)[1]
    grants = (
        [f"GRANT SELECT, DELETE ON {name} TO dw_app"]
        if purgeable
        else [f"REVOKE ALL ON {name} FROM dw_app", f"GRANT SELECT (id) ON {name} TO dw_app"]
    )
    return [
        f"CREATE TABLE {name} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL{columns})",
        f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{short} ON {name} USING ({_TENANT})",
        *grants,
    ]


async def _violations_after(
    db_urls: DatabaseUrls,
    statements: list[str],
    *,
    purge: Mapping[str, OffboardingExclusion] | None = None,
    export: Mapping[str, str] | None = None,
    predating: Mapping[str, str] | None = None,
    term_of: TermOf | None = None,
) -> list[str]:
    policy = _pinned_policy()
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text("SET LOCAL ROLE dw_migrator"))
            for statement in statements:
                await conn.execute(sa.text(statement))
            await conn.execute(sa.text("RESET ROLE"))
            found = await offboarding_violations(
                conn,
                purge if purge is not None else STUDIO_EXCLUSIONS,
                export if export is not None else EXPORT_EXCLUSIONS,
                predating if predating is not None else _PLATFORM_PREDATING,
                term_of or (policy.term),
            )
            await conn.rollback()
    finally:
        await admin.dispose()
    return found


@pytest.mark.parametrize("schema", ["studio", "platform"])
async def test_a_table_read_by_column_and_not_deleted_is_named_until_listed(
    db_urls: DatabaseUrls, schema: str
) -> None:
    """R4.1 (studio), R4.3 (a platform table that does not predate the rule):
    both sides named, and both exclusions, checked, make it pass."""
    rule = "R4.1" if schema == "studio" else "R4.3"
    parent, probe = f"{schema}.ob_parent", f"{schema}.ob_probe"
    statements = [
        *_table(parent),
        *_table(
            probe,
            columns=f", parent_id uuid REFERENCES {parent} (id) ON DELETE CASCADE",
            purgeable=False,
        ),
    ]
    found = await _violations_after(db_urls, statements)
    assert f"{rule} {probe} is not exported and has no export exclusion" in found
    assert f"{rule} {probe} is not purged and has no purge exclusion" in found

    listed = await _violations_after(
        db_urls,
        statements,
        purge={probe: OffboardingExclusion(reason="probe", cascade_from=parent)},
        export={probe: "probe: holds no customer data"},
    )
    assert [v for v in listed if probe in v] == [], listed


@pytest.mark.parametrize("deletes", ["RESTRICT", "NO ACTION"])
async def test_a_blocking_edge_against_the_purge_order_is_named(
    db_urls: DatabaseUrls, deletes: str
) -> None:
    """R4.2: the adapter deletes `studio.ob_a` before `studio.ob_b` (catalog
    order), so `ob_b -> ob_a` blocks and `ob_a -> ob_b` does not. The edge is
    made in the transaction, so only a check reading pg_constraint can see it."""
    against = await _violations_after(
        db_urls,
        [
            *_table("studio.ob_a"),
            *_table(
                "studio.ob_b",
                columns=f", a_id uuid REFERENCES studio.ob_a (id) ON DELETE {deletes}",
            ),
        ],
    )
    assert [v for v in against if v.startswith("R4.2")] == [
        "R4.2 ob_b_a_id_fkey: studio.ob_a is deleted before studio.ob_b references it"
    ]
    along = await _violations_after(
        db_urls,
        [
            *_table("studio.ob_b"),
            *_table(
                "studio.ob_a",
                columns=f", b_id uuid REFERENCES studio.ob_b (id) ON DELETE {deletes}",
            ),
        ],
    )
    assert [v for v in along if v.startswith("R4.2")] == []


async def test_an_exclusion_the_catalog_does_not_confirm_is_named(db_urls: DatabaseUrls) -> None:
    """R4.4: a function that is not there, a cascade that is RESTRICT, a kept
    row that names another table's term or carries an edge that rewrites it."""
    statements = [
        *_table("studio.ob_parent"),
        *_table(
            "studio.ob_restrict",
            columns=", parent_id uuid REFERENCES studio.ob_parent (id) ON DELETE RESTRICT",
            purgeable=False,
        ),
        *_table("studio.ob_function", purgeable=False),
        *_table(
            "studio.ob_kept",
            columns=", parent_id uuid REFERENCES studio.ob_parent (id) ON DELETE CASCADE",
            purgeable=False,
        ),
    ]
    found = await _violations_after(
        db_urls,
        statements,
        purge={
            "studio.ob_restrict": OffboardingExclusion(
                reason="probe", cascade_from="studio.ob_parent"
            ),
            "studio.ob_function": OffboardingExclusion(
                reason="probe", function="platform.no_such_fn"
            ),
            "studio.ob_kept": OffboardingExclusion(reason="probe", kept="platform.audit_events"),
        },
    )
    assert (
        "R4.4 studio.ob_restrict: no ON DELETE CASCADE to studio.ob_parent that the lane deletes"
        in found
    )
    assert (
        "R4.4 studio.ob_function: platform.no_such_fn is not a deleting step of the lane" in found
    )
    assert "R4.4 studio.ob_kept: kept without an enforced term of its own" in found
    assert any(v.startswith("R4.4 studio.ob_kept: kept, yet") for v in found), found
    with pytest.raises(ValueError):
        OffboardingExclusion(reason=" ", kept="studio.ob_kept")
    with pytest.raises(ValueError):
        OffboardingExclusion(reason="two ways", kept="a.b", function="a.f")


async def test_a_kept_table_that_blocks_the_purge_is_named(db_urls: DatabaseUrls) -> None:
    """R4.2: a table kept for its term, holding a RESTRICT edge to a table the
    lane deletes, makes that delete fail."""
    term = RetentionTerm(days=30, enforced=True)
    found = await _violations_after(
        db_urls,
        [
            *_table("studio.ob_parent"),
            *_table(
                "studio.ob_kept",
                columns=", parent_id uuid REFERENCES studio.ob_parent (id) ON DELETE RESTRICT",
                purgeable=False,
            ),
        ],
        purge={"studio.ob_kept": OffboardingExclusion(reason="probe", kept="studio.ob_kept")},
        export={"studio.ob_kept": "probe"},
        term_of=lambda key: term if key == "studio.ob_kept" else None,
    )
    assert found == [
        "R4.2 ob_kept_parent_id_fkey: studio.ob_parent is deleted before studio.ob_kept"
        " references it"
    ]


async def test_rows_for_tables_gone_or_handled_are_named(db_urls: DatabaseUrls) -> None:
    """R4.5, and R4.6: a predating row for a table made after the rule."""
    found = await _violations_after(
        db_urls,
        [*_table("studio.ob_handled"), *_table("platform.ob_new")],
        purge={
            "studio.ob_gone": OffboardingExclusion(reason="probe", function="platform.x"),
            "studio.ob_handled": OffboardingExclusion(reason="probe", function="platform.x"),
        },
        export={"studio.ob_gone": "probe", "studio.ob_handled": "probe"},
        predating={**_PLATFORM_PREDATING, "platform.ob_gone": "probe", "platform.ob_new": "probe"},
    )
    for line in (
        "R4.5 purge exclusion studio.ob_gone names no table",
        "R4.5 purge exclusion studio.ob_handled names a table the lane purges",
        "R4.5 export exclusion studio.ob_gone names no table",
        "R4.5 export exclusion studio.ob_handled names a table the lane exports",
        "R4.5 predating platform.ob_gone names no table",
        "R4.6 platform.ob_new postdates the rule",
    ):
        assert line in found, (line, found)
