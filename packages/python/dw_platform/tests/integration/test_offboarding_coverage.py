"""Offboarding reaches every tenant table of every schema (studio-skeleton R4,
foundations-hardening R11.14, R11.16).

The offboarding lane exports then purges what the catalog says `dw_app` may
SELECT and DELETE. A table it may only read by column, or may not delete from,
is skipped without a word, and that tenant's rows outlive the tenant. So every
such table is either handled or listed, with how it loses its rows, and the
listing is checked against the running catalog both ways:

- the export and the purge are judged apart, because being deleted another way
  says nothing about being handed back to the customer first;
- a purge exclusion names one way: the table it cascades from, the function
  that deletes it, or the retention fragment that keeps it for a term; a
  cascade reaches a table the lane deletes through ON DELETE CASCADE keys only,
  one link at a time;
- the one table the lane neither exports nor deletes, the offboarding request
  itself (`_NEVER_PURGE`), is the only one;
- every RESTRICT and NO ACTION edge the catalog holds (never a copied list,
  failure-modes #0) runs the way the adapter deletes, read from the one function
  `purge_rows` walks.

Every check runs on the migrated checkout, then on defects planted in a
transaction that rolls back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

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

# The one table the lane neither exports nor deletes (R11.16): the request it
# is carrying out. A second one here would be a table no check looks at.
_THE_REQUEST = frozenset({("platform", "tenant_offboarding_requests")})

# Every schema but the system's (foundations-hardening R11.14): a tenant table in
# `memory`, `knowledge` or a product context's schema is as much the customer's
# as one in `studio`, and reading two schemas made this check blind to the rest
# (discovery/09, failure-modes #0).
_TENANT_TABLES = sa.text(
    """
    SELECT n.nspname || '.' || c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
      AND c.relkind IN ('r', 'p') AND NOT c.relispartition
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'tenant_id' AND NOT a.attisdropped)
    """
)

# Asked per table of `_TENANT_TABLES`, apart from the lane's own query, so the two
# are not blind in the same place: `has_table_privilege` is false for a table
# `dw_app` reads only by column, which the lane's catalog then skips.
_READ_BY_COLUMN_ONLY = sa.text(
    "SELECT has_any_column_privilege('dw_app', CAST(:t AS regclass), 'SELECT')"
    "   AND NOT has_table_privilege('dw_app', CAST(:t AS regclass), 'SELECT')"
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

TermOf = Callable[[str], RetentionTerm | None]


async def offboarding_violations(
    conn: AsyncConnection,
    purge_exclusions: Mapping[str, OffboardingExclusion],
    export_exclusions: Mapping[str, str],
    term_of: TermOf,
    never_purge: frozenset[tuple[str, str]] = _NEVER_PURGE,
) -> list[str]:
    """R4.1-R4.5 and R11.14, R11.16, one line per defect."""
    async with AsyncSession(bind=conn) as session:
        order = await SqlTenantOffboarding(
            session_factory=None,  # type: ignore[arg-type]
            scopes=OFFBOARDING_SCOPES,
        ).purge_order(session)
    position = {step: at for at, step in enumerate(order)}
    tables = set((await conn.execute(_TENANT_TABLES)).scalars().all())
    never = {f"{schema}.{table}" for schema, table in never_purge}
    exported = {
        f"{row.schemaname}.{row.tablename}"
        for row in (await conn.execute(_CATALOG_EXPORTABLE)).all()
    } - never
    functions = set((await conn.execute(_FUNCTIONS)).scalars().all())
    edges = (await conn.execute(_FOREIGN_KEYS)).all()
    found: list[str] = []

    # R11.16: the request is the one table nothing exports or deletes.
    if never_purge != _THE_REQUEST:
        found.append(f"R11.16 _NEVER_PURGE holds {sorted(never)}, not the request alone")

    # R11.14: column-only SELECT, in every schema and predating or not.
    for table in sorted(tables):
        if await conn.scalar(_READ_BY_COLUMN_ONLY, {"t": table}):
            found.append(f"R11.14 {table} is read by column only")

    # R4.1, R4.3 (R11.14 outside `studio` and `platform`): each side handled, or
    # listed; the request, the lane's own job, only on the export side (R11.16).
    for table in sorted(tables):
        schema = table.split(".", 1)[0]
        rule = {"studio": "R4.1", "platform": "R4.3"}.get(schema, "R11.14")
        if table not in exported and table not in export_exclusions:
            found.append(f"{rule} {table} is not exported and has no export exclusion")
        if table not in position and table not in purge_exclusions and table not in never:
            found.append(f"{rule} {table} is not purged and has no purge exclusion")

    def cascades(table: str, parent: str) -> bool:
        return any(
            e.referencing == table and e.referenced == parent and e.confdeltype == "c"
            for e in edges
        )

    # R4.4 (R11.16): a cascade reaches a table the lane deletes, every link an
    # ON DELETE CASCADE key, read one link at a time.
    def cascade_reaches_the_lane(table: str, seen: frozenset[str] = frozenset()) -> bool:
        way = purge_exclusions.get(table)
        if way is None or way.cascade_from is None or table in seen:
            return False
        parent = way.cascade_from
        if not cascades(table, parent):
            return False
        return parent in position or cascade_reaches_the_lane(parent, seen | {table})

    # Where the lane's order deletes a table, along the same chain.
    def deleted_at(table: str, seen: frozenset[str] = frozenset()) -> int | None:
        if table in position:
            return position[table]
        way = purge_exclusions.get(table)
        if way is None or table in seen:
            return None
        if way.cascade_from is not None:
            return deleted_at(way.cascade_from, seen | {table})
        if way.function is not None:
            return position.get(way.function)
        return None

    # R4.4: every purge exclusion is the way the catalog says it is.
    for table, way in sorted(purge_exclusions.items()):
        if way.cascade_from is not None and not cascade_reaches_the_lane(table):
            found.append(
                f"R4.4 {table}: no ON DELETE CASCADE to {way.cascade_from} that the lane deletes"
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
    """R4.1-R4.5 and R11.16 on the migrated checkout: no table is let off."""
    policy = _pinned_policy()
    async with migrator.connect() as conn:
        found = await offboarding_violations(
            conn, STUDIO_EXCLUSIONS, EXPORT_EXCLUSIONS, policy.term
        )
    assert found == []


_ENVELOPES = "platform.secret_envelopes"


@pytest.mark.parametrize("dropped", ["purge", "export"])
async def test_the_envelopes_need_both_their_rows(migrator: AsyncEngine, dropped: str) -> None:
    """connections-and-vault R1.6 (CV2): the envelopes are neither exported nor
    deleted by the lane; without either row the coverage names the table."""
    policy = _pinned_policy()
    purge = {k: v for k, v in STUDIO_EXCLUSIONS.items() if dropped != "purge" or k != _ENVELOPES}
    export = {k: v for k, v in EXPORT_EXCLUSIONS.items() if dropped != "export" or k != _ENVELOPES}
    assert STUDIO_EXCLUSIONS[_ENVELOPES].cascade_from == "platform.connections"
    async with migrator.connect() as conn:
        found = await offboarding_violations(conn, purge, export, policy.term)
    assert found, f"dropping the {dropped} row of {_ENVELOPES} went unnoticed"
    assert all(_ENVELOPES in line for line in found), found


_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _table(name: str, *, columns: str = "", purgeable: bool = True) -> list[str]:
    """A tenant table with a `tenant_isolation_*` policy and, when `purgeable`,
    SELECT and DELETE for dw_app; otherwise no privilege at all, so the lane
    neither exports nor deletes it. Column-only SELECT is not this shape: it is
    named whatever is listed (R11.14), and `_column_only` makes it."""
    short = name.split(".", 1)[1]
    grants = (
        [f"GRANT SELECT, DELETE ON {name} TO dw_app"]
        if purgeable
        else [f"REVOKE ALL ON {name} FROM dw_app"]
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
    term_of: TermOf | None = None,
    never_purge: frozenset[tuple[str, str]] = _NEVER_PURGE,
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
                # A probe's rows are added to the real ones, which the
                # migrated catalog still needs (`platform.secret_envelopes`).
                {**STUDIO_EXCLUSIONS, **(purge or {})},
                {**EXPORT_EXCLUSIONS, **(export or {})},
                term_of or (policy.term),
                never_purge,
            )
            await conn.rollback()
    finally:
        await admin.dispose()
    return found


@pytest.mark.parametrize("table", ["object_defs", "field_defs", "picklist_options", "records"])
async def test_a_custom_object_table_dw_app_may_not_delete_is_named(
    db_urls: DatabaseUrls, table: str
) -> None:
    """custom-objects R4.4: the four tables take the lane's default step, by
    the DELETE `dw_app` holds; without it the table is named, by name."""
    found = await _violations_after(db_urls, [f"REVOKE DELETE ON studio.{table} FROM dw_app"])
    assert f"R4.1 studio.{table} is not purged and has no purge exclusion" in found


@pytest.mark.parametrize("schema", ["studio", "platform"])
async def test_a_table_the_lane_neither_reads_nor_deletes_is_named_until_listed(
    db_urls: DatabaseUrls, schema: str
) -> None:
    """R4.1 (studio), R4.3 (platform): both sides named, and both exclusions,
    checked, make it pass."""
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
async def test_a_blocking_edge_runs_the_lane_s_way_in_either_direction(
    db_urls: DatabaseUrls, deletes: str
) -> None:
    """R4.2 with foundations-hardening R11.4: the order is derived from
    pg_constraint, so an edge in either direction between `studio.ob_a` and
    `studio.ob_b` leaves no violation. Name order would delete `ob_a` first,
    so ordering by name instead of by the catalog turns the first case red. The
    edge is made in the transaction, so only a check reading pg_constraint can
    see it."""
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
    assert [v for v in against if v.startswith("R4.2")] == []
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
        term_of=lambda key: term if key == "studio.ob_kept" else _pinned_policy().term(key),
    )
    assert found == [
        "R4.2 ob_kept_parent_id_fkey: studio.ob_parent is deleted before studio.ob_kept"
        " references it"
    ]


async def test_rows_for_tables_gone_or_handled_are_named(db_urls: DatabaseUrls) -> None:
    """R4.5."""
    found = await _violations_after(
        db_urls,
        [*_table("studio.ob_handled")],
        purge={
            "studio.ob_gone": OffboardingExclusion(reason="probe", function="platform.x"),
            "studio.ob_handled": OffboardingExclusion(reason="probe", function="platform.x"),
        },
        export={"studio.ob_gone": "probe", "studio.ob_handled": "probe"},
    )
    for line in (
        "R4.5 purge exclusion studio.ob_gone names no table",
        "R4.5 purge exclusion studio.ob_handled names a table the lane purges",
        "R4.5 export exclusion studio.ob_gone names no table",
        "R4.5 export exclusion studio.ob_handled names a table the lane exports",
    ):
        assert line in found, (line, found)


# foundations-hardening ticket 10 (FH43): the rows that replaced the predating
# list, each needed.
_PREDATING_PURGE = (
    "platform.approval_decision_codes",
    "platform.approval_view_receipts",
    "platform.audit_events",
    "platform.channel_deliveries",
    "platform.channel_preferences",
    "platform.notifications",
    "platform.support_grants",
)
_PREDATING_EXPORT = ("platform.channel_preferences", "platform.tenant_offboarding_requests")


@pytest.mark.parametrize(
    ("side", "table"),
    [("purge", table) for table in _PREDATING_PURGE]
    + [("export", table) for table in _PREDATING_EXPORT],
)
async def test_each_row_that_replaced_the_predating_list_is_needed(
    migrator: AsyncEngine, side: str, table: str
) -> None:
    """R11.16 (FH43): without its row, the table is named, and nothing else."""
    policy = _pinned_policy()
    purge = {k: v for k, v in STUDIO_EXCLUSIONS.items() if side != "purge" or k != table}
    export = {k: v for k, v in EXPORT_EXCLUSIONS.items() if side != "export" or k != table}
    assert table in (STUDIO_EXCLUSIONS if side == "purge" else EXPORT_EXCLUSIONS)
    async with migrator.connect() as conn:
        found = await offboarding_violations(conn, purge, export, policy.term)
    assert found, f"dropping the {side} row of {table} went unnoticed"
    assert all(table in line for line in found), found


async def test_the_sod_waivers_are_purged_by_a_step_of_the_lane(migrator: AsyncEngine) -> None:
    """R11.16 (FH43): the table is declared by a step, so it needs no row."""
    factory = async_sessionmaker(migrator)
    async with factory() as session:
        order = await SqlTenantOffboarding(
            session_factory=factory, scopes=OFFBOARDING_SCOPES
        ).purge_order(session)
    assert "platform.purge_tenant_sod_waivers" in order
    assert "platform.sod_waivers" in order
    assert "platform.sod_waivers" not in STUDIO_EXCLUSIONS


@pytest.mark.parametrize("middle", ["CASCADE", "SET NULL"])
async def test_a_two_link_cascade_is_checked_link_by_link(
    db_urls: DatabaseUrls, middle: str
) -> None:
    """R11.16 (FH43): `ob_leaf` cascades from `ob_mid`, which cascades from
    `ob_root`, which the lane deletes. With the second link SET NULL the leaf's
    rows outlive the purge, and the leaf is named."""
    statements = [
        *_table("platform.ob_root"),
        *_table(
            "platform.ob_mid",
            columns=", root_id uuid REFERENCES platform.ob_root (id) ON DELETE CASCADE",
            purgeable=False,
        ),
        *_table(
            "platform.ob_leaf",
            columns=f", mid_id uuid REFERENCES platform.ob_mid (id) ON DELETE {middle}",
            purgeable=False,
        ),
    ]
    found = await _violations_after(
        db_urls,
        statements,
        purge={
            "platform.ob_mid": OffboardingExclusion(
                reason="probe", cascade_from="platform.ob_root"
            ),
            "platform.ob_leaf": OffboardingExclusion(
                reason="probe", cascade_from="platform.ob_mid"
            ),
        },
        export={"platform.ob_mid": "probe", "platform.ob_leaf": "probe"},
    )
    if middle == "CASCADE":
        assert found == [], found
    else:
        assert found == [
            "R4.4 platform.ob_leaf: no ON DELETE CASCADE to platform.ob_mid that the lane deletes"
        ]


async def test_a_second_table_the_lane_never_purges_is_named(db_urls: DatabaseUrls) -> None:
    """R11.16 (FH43): the request is the one table let off the purge side."""
    assert _NEVER_PURGE == _THE_REQUEST
    found = await _violations_after(
        db_urls, [], never_purge=_NEVER_PURGE | {("platform", "feedback")}
    )
    assert any(line.startswith("R11.16 _NEVER_PURGE holds") for line in found), found


# discovery/09's probe shape (`db/bench/offboarding/bench_offboarding.py probe`):
# a table `dw_app` reads by column only is skipped by `has_table_privilege`, so the
# lane neither exported nor purged it, and only `studio` was ever looked at.
_REGRANT_BY_COLUMN = (
    "DO $$ DECLARE cols text; BEGIN"
    " SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) INTO cols"
    " FROM pg_attribute WHERE attrelid = 'platform.feedback'::regclass"
    " AND attnum > 0 AND NOT attisdropped;"
    " EXECUTE 'REVOKE SELECT ON platform.feedback FROM dw_app';"
    " EXECUTE 'GRANT SELECT (' || cols || ') ON platform.feedback TO dw_app';"
    " END $$"
)


def _column_only(name: str) -> list[str]:
    short = name.split(".", 1)[1]
    return [
        f"CREATE TABLE {name} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL, body text)",
        f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{short} ON {name} USING ({_TENANT})",
        f"REVOKE ALL ON {name} FROM dw_app",
        f"GRANT SELECT (id, body), DELETE ON {name} TO dw_app",
    ]


@pytest.mark.parametrize(
    ("table", "statements"),
    [
        ("studio.ob_cols", _column_only("studio.ob_cols")),
        ("memory.ob_cols", _column_only("memory.ob_cols")),
        # A platform table that dw_app read as a table, now read through every column.
        ("platform.feedback", [_REGRANT_BY_COLUMN]),
    ],
    ids=["studio", "memory", "platform"],
)
async def test_a_table_read_by_column_only_is_named_in_every_schema(
    db_urls: DatabaseUrls, table: str, statements: list[str]
) -> None:
    """foundations-hardening R11.14 (FH41): wherever the table lives,
    column-only SELECT is named."""
    found = await _violations_after(db_urls, statements)
    assert f"R11.14 {table} is read by column only" in found, found
