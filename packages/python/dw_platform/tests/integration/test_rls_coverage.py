"""Every tenant table has RLS — asked of the catalog, not of the migrations.

`scripts/verify_invariants.py` reads migration TEXT, which is the right thing
for a check that runs without a database and catches a `CREATE TABLE` that
forgot its policy. It cannot see a table the text never names.

A partition is exactly that table. `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
on a partitioned parent applies its policies to rows reached THROUGH the parent;
a partition addressed by its own name uses its own settings. Both default
partitions had none, and `dw_app` holds SELECT on them, so this returned every
tenant's rows with no `app.tenant_id` set at all:

    SELECT count(*) FROM platform.audit_events_default;

Found by trying it. This test is what makes the next one fail loudly — including
a partition added months from now, which Postgres will not police on its own.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from studio_catalog import studio_table_violations

from dw_platform.adapters.persistence.tenant_session import (
    TenantScope,
    TenantWideLane,
    TenantWideScopeRegistry,
    bind_actor,
    bind_tenant,
    tenant_wide_scope,
)
from dw_platform.testing.members import TENANT_MEMBER_SQL, tenant_member_params
from dw_platform.testing.rbac import assign, plant_membership, plant_person, plant_tenant, role_id
from dw_platform.testing.record_objects import plant_object

pytestmark = pytest.mark.integration

# Every table with a `tenant_id` column, in whatever schema it lives. No schema
# is named: a hand-kept list of schemas is blind to the one added after it, the
# same blindness as the text checker above, one level up. `pg_*` is dropped
# whole because Postgres refuses to create a schema with that prefix, so the
# exclusion hides nothing a migration can make — it removes `pg_catalog`,
# `pg_toast*` and other sessions' `pg_temp_*`.
_TENANT_TABLES = sa.text(
    """
    SELECT n.nspname AS schema, c.relname AS name,
           c.relrowsecurity AS enabled, c.relforcerowsecurity AS forced
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p')
      AND NOT starts_with(n.nspname, 'pg_')
      AND n.nspname <> 'information_schema'
      AND EXISTS (
          SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
      )
    ORDER BY 1, 2
    """
)

# The floor discovery must clear, not the list: the schemas the platform itself
# ships. A discovery query gone wrong fails here instead of returning nothing
# and passing every check built on top of it. `studio` since its first tenant
# table (tenant-config ticket 02; studio-skeleton R2.6).
_PLATFORM_SCHEMAS = frozenset({"platform", "knowledge", "memory", "studio"})


def missed_schemas(rows: Sequence[sa.Row[Any]]) -> list[str]:
    """The platform's schemas a discovery result lacks: the floor's question."""
    return sorted(_PLATFORM_SCHEMAS - {r.schema for r in rows})


async def tenant_tables(conn: AsyncConnection | AsyncSession) -> Sequence[sa.Row[Any]]:
    """Every tenant table the catalog holds — the one answer to "which tables,
    in which schemas", shared with `test_privileges.py`."""
    rows = (await conn.execute(_TENANT_TABLES)).all()
    assert rows, "found no tenant tables at all — the query is wrong, not the schema"
    missed = missed_schemas(rows)
    assert not missed, f"schema discovery missed {missed} — the query is wrong"
    return rows


async def test_a_discovery_that_skips_studio_fails_the_floor(session: AsyncSession) -> None:
    """studio-skeleton R2.6: the floor names `studio` when a discovery query
    filtered it out, and is clear on the real one."""
    rows = (await session.execute(_TENANT_TABLES)).all()
    assert missed_schemas(rows) == []
    assert missed_schemas([r for r in rows if r.schema != "studio"]) == ["studio"]


async def tenant_schemas(conn: AsyncConnection | AsyncSession) -> list[str]:
    return sorted({r.schema for r in await tenant_tables(conn)})


_POLICIES = sa.text(
    "SELECT schemaname, tablename, policyname, qual, with_check"
    " FROM pg_policies WHERE schemaname = ANY(:schemas)"
)

# The trusted per-transaction settings a policy may narrow by. All three are set
# by the backend from a verified context and none can be supplied by a caller.
#
# `app.tenant_id` is the ordinary one. `app.principal_id` exists because identity
# bootstrap has to read your own membership BEFORE a tenant is resolved — there
# is no tenant to filter by yet; a linked chat's command reads the person's own
# rows the same way, for the same reason (`_PRINCIPAL_ONLY_ON_PURPOSE` below
# lists every such policy). `app.worker_drain` is the background drain's
# deliberate escape hatch, set only by a process draining queues across tenants.
_TRUSTED_SETTINGS = (
    "current_setting('app.tenant_id'",
    "current_setting('app.principal_id'",
    "current_setting('app.worker_drain'",
)

# Record reach (record-access ticket 03; ADR-0105 decision 1) reads the actor
# kind, the principal and the `studio.acl_*` readers. None of them isolates a
# tenant on its own, so none is a trusted setting above: like the workspace
# scope below, a policy may read them only beside a pure tenant clause
# (`scope_outside_a_tenant_clause`).
_REACH_READS = (
    "current_setting('app.actor_kind'",
    "current_setting('app.user_id'",
    "studio.acl_",
)

# `app.principal_id` is trusted, but it narrows to ONE PERSON across every tenant
# they belong to, which is wider than a tenant in one direction. So a policy that
# narrows by principal and not by tenant is allowed only on rows that belong to
# the person rather than to a workspace, and each one needs a written reason.
# Both readers bind the setting per transaction from a user the server resolved:
# sign-in from a verified token, a chat command from the chat's link row.
_PRINCIPAL_SETTING = "current_setting('app.principal_id'"
_PRINCIPAL_ONLY_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("memberships", "memberships_self_select"): (
        "identity bootstrap lists the caller's own memberships before a tenant is "
        "resolved; SELECT only, and every write goes through the tenant policy"
    ),
    ("tenants", "tenants_self_select"): (
        "sign-in names the tenants of the caller's own memberships before one is "
        "chosen; SELECT only, through those memberships"
    ),
    ("workspaces", "workspaces_self_select"): (
        "sign-in names the workspaces of the caller's own memberships before one "
        "is chosen; SELECT only, through those memberships"
    ),
    ("approval_decision_codes", "approval_decision_codes_self_select"): (
        "a decision code is the person's own and the bot reads it from the chat's "
        "linked person before it knows a tenant (migration e399be8c0a2d); SELECT "
        "only, and every write runs under the tenant and workspace policy"
    ),
    ("tenant_members", "tenant_members_self_select"): (
        "sign-in reads the caller's own standing in every company before a tenant "
        "is resolved, to list only the companies where they are active (migration "
        "349080a62e41); SELECT only, so no connection changes its own status"
    ),
    ("channel_preferences", "channel_preferences_self"): (
        "the workspace a person chose for chat commands is the person's own row, "
        "read by the bot before it knows a tenant (migration 9f2becb1bf80); the FK "
        "to the membership keeps it naming a workspace the person belongs to"
    ),
}

# Policies that narrow by no setting at all. Each needs a reason, and the reason
# is what a reviewer checks — not the entry's existence. A new policy that
# isolates nothing fails this suite until somebody writes down why it should not.
_UNSCOPED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("documents", "knowledge_global_read_documents"): (
        "scope='global' is a shared corpus every tenant may read by design; "
        "publishing into it takes the knowledge.publish_global scope"
    ),
}


@pytest.fixture
async def session(db_urls: DatabaseUrls) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as opened:
            yield opened
    finally:
        await engine.dispose()


async def test_rls_covers_every_tenant_table(session: AsyncSession) -> None:
    """Including partitions, which the text-based checker cannot see — and
    including schemas nobody listed. The tables come from the catalog, every
    non-system schema with a `tenant_id` column, because a hand-kept tuple of
    schema names goes blind to the next schema exactly the way the text checker
    went blind to partitions: a table there without RLS would stay green."""
    rows = await tenant_tables(session)

    missing = [f"{r.schema}.{r.name}" for r in rows if not r.enabled]
    forced_off = [f"{r.schema}.{r.name}" for r in rows if r.enabled and not r.forced]

    assert missing == [], f"tenant tables without RLS enabled: {missing}"
    # FORCE is what stops the owning role reading straight past the policy, and
    # the owner is who runs migrations and maintenance.
    assert forced_off == [], f"tenant tables with RLS but not FORCEd: {forced_off}"


async def test_every_tenant_table_actually_has_a_policy(session: AsyncSession) -> None:
    """RLS with no policy denies everything, which is safe and unusable — and
    RLS with a policy on the parent only is what this suite exists to catch."""
    rows = await tenant_tables(session)
    schemas = sorted({r.schema for r in rows})
    policed = {
        (r.schemaname, r.tablename)
        for r in (await session.execute(_POLICIES, {"schemas": schemas})).all()
    }

    without = [f"{r.schema}.{r.name}" for r in rows if (r.schema, r.name) not in policed]

    assert without == [], f"tenant tables with no policy of their own: {without}"


async def test_a_partition_cannot_be_read_around_its_parent(
    db_urls: DatabaseUrls, session: AsyncSession
) -> None:
    """The leak itself, reproduced end to end.

    Written as `dw_app` over its OWN connection rather than `SET ROLE`: the
    migrator cannot assume that role, and more to the point the runtime never
    does either — it connects as `dw_app`, which is the identity whose reach
    this is about.
    """
    tenant = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO platform.audit_events"
            " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
            "  resource_id, occurred_at)"
            " VALUES (gen_random_uuid(), :t, gen_random_uuid(), gen_random_uuid(),"
            "         'rls.probe', 'probe', 'x', now())"
        ),
        {"t": tenant},
    )
    await session.commit()

    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            # No `app.tenant_id` set at all — the state a connection is in before
            # anything scopes it, and the state a bug would leave it in.
            through_parent = (
                await conn.execute(sa.text("SELECT count(*) FROM platform.audit_events"))
            ).scalar_one()
            await conn.rollback()
            # And by name the partition is not there to read at all: rows are
            # read through the parent, so dw_app holds nothing on a partition
            # (studio-skeleton R3.3, R3.6). Its own policy stays as the second
            # wall behind the missing grant.
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text("SELECT count(*) FROM platform.audit_events_default"))
    finally:
        await engine.dispose()

    assert through_parent == 0


async def test_every_policy_actually_consults_the_tenant_setting(
    session: AsyncSession,
) -> None:
    """Existence is not isolation.

    `USING (true)` is a policy. So is one filtering on a column nobody sets. What
    isolates is a predicate reading a setting the backend controls — asserted on
    the read side AND the write side, because a policy that reads correctly and
    writes freely lets one tenant insert rows into another's table.

    Three settings count, not one: identity bootstrap narrows by principal
    because no tenant is resolved yet, and the background drain narrows by its
    own flag. Anything narrowing by none of them needs a written reason.
    """
    rows = (await session.execute(_POLICIES, {"schemas": await tenant_schemas(session)})).all()
    assert rows, "no policies at all — the query is wrong, not the schema"

    blind_reads, blind_writes = blind_policies(rows)

    assert blind_reads == [], (
        f"policies narrowing by no trusted setting and with no written reason: {blind_reads}"
    )
    assert blind_writes == [], f"policies that do not filter writes: {blind_writes}"


def _narrows(predicate: str | None) -> bool:
    return predicate is not None and any(s in predicate for s in _TRUSTED_SETTINGS)


def blind_policies(rows: Sequence[sa.Row[Any]]) -> tuple[list[str], list[str]]:
    """The policies that read, and that write, narrowed by no trusted setting."""
    # A policy with WITH CHECK alone (`FOR INSERT`, the record template's
    # `_insert`) reads nothing; its write side is judged below.
    reads = [
        f"{r.schemaname}.{r.tablename}.{r.policyname}"
        for r in rows
        if not _narrows(r.qual)
        and not (r.qual is None and r.with_check is not None)
        and (r.tablename, r.policyname) not in _UNSCOPED_ON_PURPOSE
    ]
    writes = [
        f"{r.schemaname}.{r.tablename}.{r.policyname}"
        for r in rows
        if r.with_check is not None and not _narrows(r.with_check)
    ]
    return reads, writes


async def test_co21_a_permissive_policy_open_to_all_on_records_is_named(
    session: AsyncSession,
) -> None:
    """custom-objects R4.2 (CO21): `studio.records` is narrowed by its
    RESTRICTIVE tenant policy; a PERMISSIVE `USING (true)` beside it, made and
    rolled back here, is a blind read and a blind write the rule above names."""
    try:
        await session.execute(
            sa.text(
                "CREATE POLICY open_records ON studio.records AS PERMISSIVE"
                " USING (true) WITH CHECK (true)"
            )
        )
        rows = (await session.execute(_POLICIES, {"schemas": ["studio"]})).all()
    finally:
        await session.rollback()
    reads, writes = blind_policies(rows)
    assert reads == ["studio.records.open_records"]
    assert writes == ["studio.records.open_records"]


# custom-objects R4.2: a partition of a Studio table carries its parent's
# policies, the same in every respect but the table (ADR-0105 decision 1; the
# record template). Row security is not inherited, so only this asks.
_PARTITION_POLICIES = sa.text(
    """
    SELECT parent.relname AS parent, child.relname AS child,
           ARRAY(SELECT p.polname || ' ' || p.polpermissive::text || ' ' || p.polcmd::text
                        || ' ' || p.polroles::text
                        || ' ' || coalesce(pg_get_expr(p.polqual, p.polrelid), '')
                        || ' ' || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')
                 FROM pg_policy p WHERE p.polrelid = parent.oid ORDER BY 1) AS of_parent,
           ARRAY(SELECT p.polname || ' ' || p.polpermissive::text || ' ' || p.polcmd::text
                        || ' ' || p.polroles::text
                        || ' ' || coalesce(pg_get_expr(p.polqual, p.polrelid), '')
                        || ' ' || coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')
                 FROM pg_policy p WHERE p.polrelid = child.oid ORDER BY 1) AS of_child
    FROM pg_inherits i
    JOIN pg_class parent ON parent.oid = i.inhparent
    JOIN pg_class child ON child.oid = i.inhrelid
    JOIN pg_namespace n ON n.oid = parent.relnamespace
    WHERE n.nspname = 'studio' AND parent.relkind = 'p'
    ORDER BY 1, 2
    """
)


async def studio_partition_drift(conn: AsyncConnection | AsyncSession) -> list[str]:
    rows = (await conn.execute(_PARTITION_POLICIES)).all()
    return [
        f"studio.{r.child} differs from studio.{r.parent}"
        for r in rows
        if r.of_parent != r.of_child
    ]


async def test_every_studio_partition_holds_its_parents_policies(session: AsyncSession) -> None:
    rows = (await session.execute(_PARTITION_POLICIES)).all()
    assert {r.child for r in rows} >= {f"records_p{n}" for n in range(4)}
    assert await studio_partition_drift(session) == []


@pytest.mark.parametrize(
    ("statement", "named"),
    [
        (
            "ALTER POLICY tenant_isolation_records ON studio.records_p2 USING (true)",
            ["studio.records_p2 differs from studio.records"],
        ),
        (
            "ALTER POLICY tenant_isolation_records ON studio.records USING (true)",
            [f"studio.records_p{n} differs from studio.records" for n in range(4)],
        ),
        (
            "DROP POLICY tenant_isolation_records ON studio.records_p3",
            ["studio.records_p3 differs from studio.records"],
        ),
    ],
)
async def test_a_studio_partition_policy_bent_away_from_its_parent_is_named(
    session: AsyncSession, statement: str, named: list[str]
) -> None:
    try:
        await session.execute(sa.text(statement))
        found = await studio_partition_drift(session)
    finally:
        await session.rollback()
    assert found == named


async def test_a_connection_that_never_scopes_itself_reads_nothing(
    db_urls: DatabaseUrls, session: AsyncSession
) -> None:
    """The contract any language has to honour to be allowed near this database.

    `dw_app` does not bypass RLS, so a connection that never sets
    `app.tenant_id` should see zero rows — whatever wrote them, and whatever
    language is asking. This is what makes the database, rather than one
    application, the place tenant isolation lives.
    """
    tenant = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO platform.audit_events"
            " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
            "  resource_id, occurred_at)"
            " VALUES (gen_random_uuid(), :t, gen_random_uuid(), gen_random_uuid(),"
            "         'rls.unscoped', 'probe', 'x', now())"
        ),
        {"t": tenant},
    )
    await session.commit()

    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            seen = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM platform.audit_events WHERE action = :a"),
                    {"a": "rls.unscoped"},
                )
            ).scalar_one()
            # And the row IS there — asserted through a role that may bypass, so
            # the zero above is isolation rather than an empty table.
            assert seen == 0, "an unscoped connection read a tenant's rows"
    finally:
        await engine.dispose()

    still_there = (
        await session.execute(
            sa.text("SELECT count(*) FROM platform.audit_events WHERE action = :a"),
            {"a": "rls.unscoped"},
        )
    ).scalar_one()
    assert still_there == 1, "the probe row vanished, so the zero above proved nothing"


# --- The workspace scope: a setting that widens, so it is never trusted alone --
#
# A context may narrow its tables by workspace as well as tenant. The offboarding
# lane sets `app.workspace_scope = 'tenant'` to read every workspace of the one
# tenant it is working on, and nothing else sets it. A policy may read the scope
# only as the alternative to its workspace clause, inside an AND whose other side
# is the tenant clause:
#
#     tenant_id = <app.tenant_id> AND (workspace_id = <app.workspace_id>
#                                      OR <app.workspace_scope> = 'tenant')
#
# Read anywhere else, it opens a tenant's rows to any transaction that sets it.
# The rules below apply to every schema `tenant_schemas` discovers.
_TENANT_SETTING = "current_setting('app.tenant_id'"
_WORKSPACE_SETTING = "current_setting('app.workspace_id'"
_SCOPE_SETTING = "current_setting('app.workspace_scope'"


def _closing(expr: str, opening: int) -> int:
    """Index of the parenthesis closing the one at `opening`, skipping quoted
    literals (Postgres doubles a quote inside one)."""
    depth, i, quoted = 0, opening, False
    while i < len(expr):
        c = expr[i]
        if quoted:
            if c == "'" and expr[i + 1 : i + 2] == "'":
                i += 1
            elif c == "'":
                quoted = False
        elif c == "'":
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError(f"unbalanced policy expression: {expr}")


def _top_level(expr: str) -> tuple[str | None, list[str]]:
    """The outermost operator of a policy expression and its operands.

    Postgres prints a policy fully parenthesised (measured on 16: `a AND b OR c`
    comes back as `((a AND b) OR c)`), so once the parentheses wrapping the whole
    expression come off, the operators left at depth zero are all one operator.
    The operator is None for a single term.
    """
    s = expr.strip()
    while s.startswith("(") and _closing(s, 0) == len(s) - 1:
        s = s[1:-1].strip()
    operator: str | None = None
    parts: list[str] = []
    depth, start, i, quoted = 0, 0, 0, False
    while i < len(s):
        c = s[i]
        if quoted:
            if c == "'" and s[i + 1 : i + 2] == "'":
                i += 1
            elif c == "'":
                quoted = False
        elif c == "'":
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            word = next((w for w in (" AND ", " OR ") if s.startswith(w, i)), None)
            if word is not None:
                found = word.strip()
                assert operator in (None, found), f"mixed operators at one level: {expr}"
                operator = found
                parts.append(s[start:i].strip())
                i += len(word)
                start = i
                continue
        i += 1
    parts.append(s[start:].strip())
    return operator, parts


def scope_outside_a_tenant_clause(policies: Sequence[sa.Row[Any]]) -> list[str]:
    """Policies that read the scope, or record reach (`_REACH_READS`), anywhere
    but beside a pure tenant clause."""
    bad = []
    for r in policies:
        for expr in (r.qual, r.with_check):
            if expr is None or not any(s in expr for s in (_SCOPE_SETTING, *_REACH_READS)):
                continue
            operator, parts = _top_level(expr)
            tenant_clause = [
                p
                for p in parts
                if _TENANT_SETTING in p
                and not any(s in p for s in (_SCOPE_SETTING, *_REACH_READS))
                and _top_level(p)[0] != "OR"
            ]
            if operator != "AND" or not tenant_clause:
                bad.append(f"{r.schemaname}.{r.tablename}.{r.policyname}")
                break
    return bad


def workspace_tables_blind_to_scope(policies: Sequence[sa.Row[Any]]) -> list[str]:
    """Tables narrowed by workspace with no policy reading the scope: the
    offboarding lane would export none of their rows, delete none, and the purge
    of the tenant's workspaces would then CASCADE them away unexported. In
    schema `studio`, a table narrowed by the principal or by record reach (a
    `studio.acl_*` reader) is narrowed too (record-access ticket 03, (q));
    `platform` keeps the workspace rule alone."""

    def reads(r: sa.Row[Any], setting: str) -> bool:
        return any(e is not None and setting in e for e in (r.qual, r.with_check))

    def narrowing(r: sa.Row[Any]) -> bool:
        if reads(r, _WORKSPACE_SETTING):
            return True
        return r.schemaname == "studio" and (
            reads(r, "current_setting('app.user_id'") or reads(r, "studio.acl_")
        )

    narrowed = {f"{r.schemaname}.{r.tablename}" for r in policies if narrowing(r)}
    scoped = {f"{r.schemaname}.{r.tablename}" for r in policies if reads(r, _SCOPE_SETTING)}
    return sorted(narrowed - scoped)


async def test_the_workspace_scope_only_ever_sits_beside_a_tenant_clause(
    session: AsyncSession,
) -> None:
    rows = (await session.execute(_POLICIES, {"schemas": await tenant_schemas(session)})).all()
    assert scope_outside_a_tenant_clause(rows) == [], (
        "policies reading app.workspace_scope outside `tenant AND (workspace OR scope)`"
    )


async def test_a_workspace_narrowed_table_lets_offboarding_read_every_workspace(
    session: AsyncSession,
) -> None:
    rows = (await session.execute(_POLICIES, {"schemas": await tenant_schemas(session)})).all()
    assert workspace_tables_blind_to_scope(rows) == [], (
        "tables narrowed by app.workspace_id with no policy reading app.workspace_scope"
    )


_TENANT = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_WORKSPACE = "workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid"
_SCOPE = "current_setting('app.workspace_scope', true) = 'tenant'"


async def test_the_scope_rules_catch_the_wrong_shapes(session: AsyncSession) -> None:
    """The two rules above pass on today's schema because no table is narrowed
    by workspace yet, which proves nothing about them. These are real
    Postgres-printed policies of each shape, made and rolled back in one
    transaction."""
    shapes = {
        "spec": f"{_TENANT} AND ({_WORKSPACE} OR {_SCOPE})",
        "tenant_or_scope": f"{_TENANT} OR {_SCOPE}",
        "unparenthesised": f"{_TENANT} AND {_WORKSPACE} OR {_SCOPE}",
        "weak_tenant": f"({_TENANT} OR {_SCOPE}) AND ({_WORKSPACE} OR {_SCOPE})",
        "scope_alone": _SCOPE,
        # A tenant clause widened by something other than the scope.
        "loose_tenant": f"({_TENANT} OR workspace_id IS NULL) AND ({_WORKSPACE} OR {_SCOPE})",
    }
    probe, blind = "public.scope_rules_probe", "public.scope_rules_blind"
    try:
        for table in (probe, blind):
            await session.execute(
                sa.text(f"CREATE TABLE {table} (tenant_id uuid, workspace_id uuid)")
            )
        for name, using in shapes.items():
            await session.execute(sa.text(f"CREATE POLICY {name} ON {probe} USING ({using})"))
        await session.execute(
            sa.text(
                f"CREATE POLICY write_side ON {probe} FOR INSERT WITH CHECK ({_TENANT} OR {_SCOPE})"
            )
        )
        await session.execute(
            sa.text(f"CREATE POLICY ws_only ON {blind} USING ({_TENANT} AND {_WORKSPACE})")
        )
        rows = [
            r
            for r in (await session.execute(_POLICIES, {"schemas": ["public"]})).all()
            if r.tablename.startswith("scope_rules_")
        ]

        assert sorted(scope_outside_a_tenant_clause(rows)) == [
            "public.scope_rules_probe.loose_tenant",
            "public.scope_rules_probe.scope_alone",
            "public.scope_rules_probe.tenant_or_scope",
            "public.scope_rules_probe.unparenthesised",
            "public.scope_rules_probe.weak_tenant",
            "public.scope_rules_probe.write_side",
        ]
        assert workspace_tables_blind_to_scope(rows) == ["public.scope_rules_blind"]
    finally:
        await session.rollback()


async def test_a_policy_narrowed_by_principal_alone_has_a_written_reason(
    session: AsyncSession,
) -> None:
    """A principal-only policy is a person-wide read, so it is listed with why.

    A new table whose only policy reads `app.principal_id` would otherwise pass
    `test_every_policy_actually_consults_the_tenant_setting` unexamined."""
    rows = (await session.execute(_POLICIES, {"schemas": await tenant_schemas(session)})).all()

    def principal_only(predicate: str | None) -> bool:
        return (
            predicate is not None
            and _PRINCIPAL_SETTING in predicate
            and _TENANT_SETTING not in predicate
        )

    found = {
        (r.tablename, r.policyname)
        for r in rows
        if principal_only(r.qual) or principal_only(r.with_check)
    }
    assert found == set(_PRINCIPAL_ONLY_ON_PURPOSE), (
        f"principal-only policies without a written reason: "
        f"{sorted(found - set(_PRINCIPAL_ONLY_ON_PURPOSE))}; "
        f"reasons for policies that no longer exist: "
        f"{sorted(set(_PRINCIPAL_ONLY_ON_PURPOSE) - found)}"
    )


async def test_a_connection_that_binds_no_principal_reads_no_chat_preference(
    db_urls: DatabaseUrls, session: AsyncSession
) -> None:
    """The principal-only table's version of the unscoped-connection contract
    above: a row exists, and `dw_app` with no `app.principal_id` sees none."""
    user, tenant, workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for statement, params in (
        (
            "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'x')",
            {"u": user, "s": f"rls|{user}"},
        ),
        (
            "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :slug, 'T')",
            {"t": tenant, "slug": f"rls-{tenant.hex[:8]}"},
        ),
        (
            "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
            " VALUES (:w, :t, 'main', 'Main')",
            {"w": workspace, "t": tenant},
        ),
        (TENANT_MEMBER_SQL, tenant_member_params(tenant, user)),
        (
            "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id)"
            " VALUES (gen_random_uuid(), :t, :w, :u)",
            {"t": tenant, "w": workspace, "u": user},
        ),
        (
            "INSERT INTO platform.channel_preferences (user_id, tenant_id, workspace_id)"
            " VALUES (:u, :t, :w)",
            {"u": user, "t": tenant, "w": workspace},
        ),
    ):
        await session.execute(sa.text(statement), params)
    await session.commit()

    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            # A tenant bound is not enough either: the row is narrowed by person.
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            seen = (
                await conn.execute(sa.text("SELECT count(*) FROM platform.channel_preferences"))
            ).scalar_one()
    finally:
        await engine.dispose()

    there = (
        await session.execute(
            sa.text("SELECT count(*) FROM platform.channel_preferences WHERE user_id = :u"),
            {"u": user},
        )
    ).scalar_one()
    assert seen == 0, "a connection without a principal read a person's chat preference"
    assert there == 1, "the probe row is missing, so the zero above proved nothing"


# ---------------------------------------------------------------------------
# Tenant-wide tables (ADR 0100 point 5; studio-skeleton R9): a tenant table
# with no `workspace_id` holds rows that belong to the whole company, and says
# why here. This dict is the one list of them (DO-01).
# ---------------------------------------------------------------------------

_TENANT_WIDE_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("platform", "connections"): (
        "tầm dùng của một Kết nối vượt workspace theo thiết kế (connections-and-vault D1);"
        " workspace sở hữu là `owning_workspace_id`, giữ bởi khóa ghép RESTRICT"
    ),
    ("platform", "control_switches"): (
        "công tắc Đóng băng của cả công ty, hay Tắt khẩn của một thành phần toàn tenant; workspace"
        " của thành phần là `owning_workspace_id`, RLS không đọc (agent-lifecycle ticket 01, DO-01)"
    ),
    ("platform", "consent_records"): (
        "a person's consent is the controller's, the tenant (ADR-0124 decision 4): a "
        "withdrawal recorded in one workspace stops sends from every other"
    ),
    ("platform", "contact_suppressions"): (
        "an opt-out holds across the company (ADR-0124 decision 4): who declined in one "
        "workspace gets no message from another"
    ),
    ("memory", "item_evidence"): (
        "a link row between a memory item and its evidence; its workspace is the "
        "item's, and it is reached only through the item"
    ),
    ("platform", "agent_store"): (
        "the agent runtime's long-term store, keyed by namespace across the whole "
        "tenant rather than by one workspace"
    ),
    ("platform", "effect_keys"): (
        "an effect an idempotent request committed, keyed by its caller across the "
        "tenant; the workspace is inside the request hash (app-standards R2.16)"
    ),
    ("platform", "egress_allowed_hosts"): (
        "một Máy chủ được phép mở đích cho mọi workspace của công ty (connections-and-vault"
        " D1, ticket 03); workspace sở hữu là `owning_workspace_id`, giữ bởi khóa ghép RESTRICT"
    ),
    ("platform", "entitlements"): "what the tenant's plan includes, for the whole company",
    ("platform", "policy_overrides"): "a tenant's override of a platform policy, company-wide",
    ("platform", "secret_envelopes"): (
        "dòng con của chủ thể mang workspace (Kết nối: `owning_workspace_id`), chỉ tới qua"
        " cửa SECURITY DEFINER; connections-and-vault ticket 02"
    ),
    ("platform", "run_manifests"): (
        "bản kê lượt chạy định danh theo nội dung, dùng chung cho mọi lượt chạy cùng nội dung,"
        " ở mọi workspace (tenant-config ticket 04, DO-01)"
    ),
    ("platform", "run_manifest_keys"): (
        "khóa của bản kê lượt chạy, con của bản kê, chỉ tới qua nó (tenant-config ticket 04)"
    ),
    ("platform", "service_principals"): (
        "a service principal is an identity of the company (ADR-0103 decision 2); its "
        "workspace is `owning_workspace_id`, held by the RESTRICT composite key"
    ),
    ("platform", "role_change_requests"): (
        "đề xuất thay đổi vai trò thuộc cả công ty như vai trò nó sửa; workspace của một gán nằm"
        " trong `payload` và ở `platform.role_assignments` khi áp (tenant-rbac ticket 03, DO-01)"
    ),
    ("platform", "sod_waivers"): (
        "a separation-of-duties waiver for a person across the company's memberships"
    ),
    ("platform", "tenant_access_versions"): (
        "vai trò, quyền của vai trò và phiên bản quyền thuộc cả công ty; neo workspace nằm ở "
        "`platform.role_assignments` (tenant-rbac ticket 02, DO-01)"
    ),
    ("platform", "tenant_daily_spend_guard"): "the tenant's spend for one day, all workspaces",
    ("platform", "tenant_members"): (
        "a person's standing belongs to the whole company, not to a workspace "
        "(org-and-principals R4.1); each membership in a workspace hangs from it"
    ),
    ("platform", "tenant_offboarding_requests"): "the request to offboard the whole tenant",
    ("platform", "tenant_role_permissions"): (
        "vai trò, quyền của vai trò và phiên bản quyền thuộc cả công ty; neo workspace nằm ở "
        "`platform.role_assignments` (tenant-rbac ticket 02, DO-01)"
    ),
    ("platform", "tenant_role_object_privileges"): (
        "quyền của vai trò thuộc cả công ty; neo workspace nằm ở gán vai trò"
        " (tenant-rbac ticket 04, DO-01)"
    ),
    ("platform", "tenant_roles"): (
        "vai trò, quyền của vai trò và phiên bản quyền thuộc cả công ty; neo workspace nằm ở "
        "`platform.role_assignments` (tenant-rbac ticket 02, DO-01)"
    ),
    ("platform", "workspaces"): "the workspace rows themselves; a workspace is not inside one",
    ("studio", "artifacts"): (
        "a Studio definition belongs to the company; its workspace is `owning_workspace_id`,"
        " held by the RESTRICT composite key (tenant-config ticket 02, DO-01)"
    ),
    ("studio", "artifact_versions"): (
        "a version of an artifact, reached only through it; its workspace is the artifact's"
    ),
    ("studio", "dependencies"): (
        "where one version uses another artifact, a child of the version; workspaces apart"
        " on purpose (a dependent in ws2 counts against deleting an artifact of ws1)"
    ),
    ("studio", "definition_manifests"): (
        "content-addressed by hash across the company; one body serves every version that"
        " seals the same content and closure"
    ),
    ("studio", "object_defs"): (
        "định nghĩa đối tượng của cả công ty; workspace của nó là `owning_workspace_id` của"
        " thành phần `object` cùng id (custom-objects ticket 02, ADR-0107 quyết 1, DO-01)"
    ),
    ("studio", "field_defs"): (
        "định nghĩa đối tượng của cả công ty: trường của một đối tượng, chỉ tới qua nó"
        " (custom-objects ticket 02, DO-01)"
    ),
    ("studio", "field_permissions"): (
        "quyền của vai trò thuộc cả công ty; neo workspace nằm ở gán vai trò"
        " (tenant-rbac ticket 04, ADR-0106 quyết 3, DO-01)"
    ),
    ("studio", "picklist_options"): (
        "định nghĩa đối tượng của cả công ty: lựa chọn của một trường, chỉ tới qua nó"
        " (custom-objects ticket 02, DO-01)"
    ),
    ("studio", "principal_scopes"): (
        "sổ tầm dẫn xuất của một chủ thể và epoch của cả tenant: tầm của một người là hợp"
        " mọi lần gán trong công ty (record-access ticket 02, ADR-0105 quyết 4, DO-01)"
    ),
    ("studio", "access_epochs"): (
        "sổ tầm dẫn xuất của một chủ thể và epoch của cả tenant: một dòng đếm mỗi công ty"
        " (record-access ticket 02, ADR-0105 quyết 4, DO-01)"
    ),
}

_TENANT_WITHOUT_WORKSPACE = sa.text(
    """
    SELECT n.nspname AS schema, c.relname AS name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
      AND NOT starts_with(n.nspname, 'pg_') AND n.nspname <> 'information_schema'
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'tenant_id' AND NOT a.attisdropped)
      AND NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                      AND a.attname = 'workspace_id' AND NOT a.attisdropped)
    ORDER BY 1, 2
    """
)

# Every table with an `owning_workspace_id`, and whether a foreign key
# `(tenant_id, owning_workspace_id) -> platform.workspaces (tenant_id, id)`
# with ON DELETE RESTRICT holds it: deleting a workspace must not take a
# company-wide definition with it.
_OWNING_WORKSPACE = sa.text(
    """
    SELECT n.nspname AS schema, c.relname AS name,
           EXISTS (
               SELECT 1 FROM pg_constraint k
               WHERE k.conrelid = c.oid AND k.contype = 'f' AND k.confdeltype = 'r'
                 AND k.confrelid = 'platform.workspaces'::regclass
                 AND (SELECT array_agg(a.attname::text ORDER BY a.attname) FROM pg_attribute a
                      WHERE a.attrelid = k.conrelid AND a.attnum = ANY(k.conkey))
                     = ARRAY['owning_workspace_id', 'tenant_id']
                 AND (SELECT array_agg(a.attname::text ORDER BY a.attname) FROM pg_attribute a
                      WHERE a.attrelid = k.confrelid AND a.attnum = ANY(k.confkey))
                     = ARRAY['id', 'tenant_id']
           ) AS held
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'owning_workspace_id' AND NOT a.attisdropped)
    ORDER BY 1, 2
    """
)


async def tenant_wide_violations(
    conn: AsyncConnection | AsyncSession, listed: dict[tuple[str, str], str]
) -> list[str]:
    """R9.1-R9.4, by name and requirement."""
    found: list[str] = []
    rows = {(r.schema, r.name) for r in (await conn.execute(_TENANT_WITHOUT_WORKSPACE)).all()}
    found += [
        f"R9.1 {s}.{t} has tenant_id and no workspace_id, and no reason"
        for s, t in sorted(rows - set(listed))
    ]
    found += [
        f"R9.2 listed {s}.{t} is gone or carries workspace_id"
        for s, t in sorted(set(listed) - rows)
    ]
    schemas = sorted({schema for schema, _ in listed})
    for p in (await conn.execute(_POLICIES, {"schemas": schemas})).all():
        reads = f"{p.qual or ''} {p.with_check or ''}"
        if (p.schemaname, p.tablename) in listed and _WORKSPACE_SETTING in reads:
            found.append(f"R9.3 {p.schemaname}.{p.tablename}.{p.policyname} reads app.workspace_id")
    found += [
        f"R9.4 {r.schema}.{r.name} has owning_workspace_id without the RESTRICT composite key"
        for r in (await conn.execute(_OWNING_WORKSPACE)).all()
        if not r.held
    ]
    return found


async def test_every_tenant_table_without_a_workspace_has_a_reason(session: AsyncSession) -> None:
    """R9.1-R9.4 on the migrated checkout, both ways."""
    assert await tenant_wide_violations(session, _TENANT_WIDE_ON_PURPOSE) == []


async def test_the_tenant_wide_checks_name_each_planted_defect(session: AsyncSession) -> None:
    """Each defect made and rolled back in one transaction, as the migrator."""
    probe_listed = {**_TENANT_WIDE_ON_PURPOSE, ("public", "tw_listed_probe"): "probe"}
    try:
        await session.execute(sa.text("CREATE TABLE public.tw_probe (tenant_id uuid)"))
        await session.execute(
            sa.text(
                "CREATE TABLE public.tw_listed_probe (tenant_id uuid, owning_workspace_id uuid)"
            )
        )
        # The shape R9.3 forbids: a company-wide row narrowed by the caller's
        # workspace, through the owning workspace RLS must never read.
        await session.execute(
            sa.text(
                "CREATE POLICY reads_workspace ON public.tw_listed_probe USING ("
                "owning_workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
            )
        )
        await session.execute(
            sa.text(
                "CREATE TABLE public.tw_cascade_probe (tenant_id uuid, owning_workspace_id uuid,"
                " workspace_id uuid)"
            )
        )
        await session.execute(
            sa.text(
                "ALTER TABLE platform.workspaces"
                " ADD CONSTRAINT uq_workspaces_probe UNIQUE (tenant_id, id)"
            )
        )
        await session.execute(
            sa.text(
                "ALTER TABLE public.tw_cascade_probe"
                " ADD FOREIGN KEY (tenant_id, owning_workspace_id)"
                " REFERENCES platform.workspaces (tenant_id, id) ON DELETE CASCADE"
            )
        )
        found = await tenant_wide_violations(session, probe_listed)
        gone = await tenant_wide_violations(
            session, {**_TENANT_WIDE_ON_PURPOSE, ("platform", "no_such_table"): "probe"}
        )
    finally:
        await session.rollback()

    assert "R9.1 public.tw_probe has tenant_id and no workspace_id, and no reason" in found
    assert "R9.3 public.tw_listed_probe.reads_workspace reads app.workspace_id" in found
    assert (
        "R9.4 public.tw_listed_probe has owning_workspace_id without the RESTRICT composite key"
        in found
    )
    assert (
        "R9.4 public.tw_cascade_probe has owning_workspace_id without the RESTRICT composite key"
        in found
    )
    assert "R9.2 listed platform.no_such_table is gone or carries workspace_id" in gone


# ---------------------------------------------------------------------------
# Studio tables (studio-skeleton R2.8, R2.11): every one is a tenant table
# under forced RLS, but the platform reference tables listed here, which hold
# no tenant's rows: `studio.artifact_kinds` since tenant-config ticket 02
# (ADR 0109 decision 1).
# ---------------------------------------------------------------------------

_PLATFORM_REFERENCE_TABLES: dict[tuple[str, str], str] = {
    ("studio", "artifact_kinds"): (
        "the platform's catalogue of Studio kinds and their gate flag; a migration of each"
        " kind's spec writes it, `dw_app` only reads (ADR-0109 decision 1)"
    ),
    ("studio", "access_input_tables"): (
        "the platform's declaration of which tables feed record reach and their trigger"
        " function; a migration writes it, `dw_app` only reads (record-access ticket 02)"
    ),
}


async def test_every_studio_table_is_a_tenant_table_under_forced_rls(
    session: AsyncSession,
) -> None:
    assert await studio_table_violations(session, _PLATFORM_REFERENCE_TABLES) == []


async def test_the_studio_table_checks_name_each_planted_defect(session: AsyncSession) -> None:
    reference = {("studio", "reference_probe"): "probe", ("studio", "gone_probe"): "probe"}
    try:
        for statement in (
            "CREATE TABLE studio.no_tenant_probe (id uuid)",
            "CREATE TABLE studio.unforced_probe (id uuid, tenant_id uuid)",
            "ALTER TABLE studio.unforced_probe ENABLE ROW LEVEL SECURITY",
            "CREATE TABLE studio.reference_probe (key text, tenant_id uuid)",
            "GRANT INSERT ON studio.reference_probe TO dw_app",
        ):
            await session.execute(sa.text(statement))
        found = await studio_table_violations(session, reference)
    finally:
        await session.rollback()

    assert "R2.8 no_tenant_probe has no tenant_id" in found
    assert "R2.8 unforced_probe does not enable and force row security" in found
    assert "R2.11 reference table reference_probe has tenant_id" in found
    assert "R2.11 dw_app may write reference table reference_probe" in found
    assert "R2.11 listed reference table gone_probe does not exist" in found


# foundations-hardening R5.3 (FH14): a policy reads each setting once per
# statement. `current_setting(` inside a sub-SELECT is an InitPlan, computed
# once; anywhere else it runs for every row and keeps the value out of the
# index condition. A setting read inside an uncorrelated sub-query (the
# membership look-up of `workspaces`) is computed once with that sub-query.


def _reads_per_row(expr: str) -> bool:
    """Whether some `current_setting(` in the expression has no enclosing
    parenthesis whose contents begin with SELECT."""
    start = 0
    while (at := expr.find("current_setting(", start)) != -1:
        start = at + 1
        depth, i, covered = 0, at - 1, False
        while i >= 0:
            if expr[i] == ")":
                depth += 1
            elif expr[i] == "(":
                if depth == 0:
                    if expr[i + 1 :].lstrip().upper().startswith("SELECT"):
                        covered = True
                        break
                else:
                    depth -= 1
            i -= 1
        if not covered:
            return True
    return False


def settings_read_per_row(policies: Sequence[sa.Row[Any]]) -> list[str]:
    return sorted(
        f"{r.schemaname}.{r.tablename}.{r.policyname}"
        for r in policies
        if any(e is not None and _reads_per_row(e) for e in (r.qual, r.with_check))
    )


async def test_every_policy_reads_its_settings_once_per_statement(session: AsyncSession) -> None:
    """Partitions included: they are in the catalog like any table, and the
    partition-making function writes the same shape (checked below)."""
    rows = (await session.execute(_POLICIES, {"schemas": await tenant_schemas(session)})).all()
    assert settings_read_per_row(rows) == []


async def test_a_per_row_setting_read_is_named(session: AsyncSession) -> None:
    """The rule above can fail: a policy of the old shape, made and rolled back
    in one transaction, is named; the wrapped shape is not."""
    try:
        await session.execute(sa.text("CREATE TABLE public.initplan_probe (tenant_id uuid)"))
        await session.execute(
            sa.text(
                "CREATE POLICY old_shape ON public.initplan_probe USING"
                " (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
        )
        await session.execute(
            sa.text(
                "CREATE POLICY new_shape ON public.initplan_probe USING"
                " (tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
            )
        )
        rows = (await session.execute(_POLICIES, {"schemas": ["public"]})).all()
        assert settings_read_per_row(rows) == ["public.initplan_probe.old_shape"]
    finally:
        await session.rollback()


async def test_a_partition_made_later_takes_the_once_per_statement_shape(
    session: AsyncSession,
) -> None:
    """`platform.ensure_time_partitions` makes next months' partitions; their
    policies come from the function's own predicate, not from this revision."""
    try:
        await session.execute(sa.text("SELECT count(*) FROM platform.ensure_time_partitions(14)"))
        rows = (await session.execute(_POLICIES, {"schemas": ["platform"]})).all()
        made = [
            r
            for r in rows
            if r.policyname.startswith("tenant_isolation_")
            and re.search(r"_\d{4}_\d{2}$", r.tablename)
        ]
        assert made, "no partition policy was made to check"
        assert settings_read_per_row(made) == []
    finally:
        await session.rollback()


# ---------------------------------------------------------------------------
# Tables private to one person (CLAUDE.md, Tenancy and authorization; ADR 0117):
# the tenant policy, and one RESTRICTIVE `tenant AND (owner OR scope)` whose
# owner is `app.user_id`, so no PERMISSIVE policy added later reopens another
# person's row. A RESTRICTIVE policy reading `app.user_id` on a table not listed
# here is named: this dict is the one list of such tables.
# ---------------------------------------------------------------------------

_PRIVATE_TO_ONE_PERSON: dict[tuple[str, str], tuple[str, str]] = {
    ("studio", "principal_scopes"): (
        "principal_id",
        "sổ tầm của một chủ thể, chỉ người đó đọc (record-access ticket 02, gate (b))",
    ),
}

_POLICY_KINDS = sa.text(
    "SELECT schemaname, tablename, policyname, permissive, cmd, qual, with_check"
    " FROM pg_policies WHERE schemaname = ANY(:schemas)"
)
_USER_SETTING = "current_setting('app.user_id'"


def _tenant_alone(expr: str) -> bool:
    return (
        _TENANT_SETTING in expr
        and _USER_SETTING not in expr
        and _SCOPE_SETTING not in expr
        and _top_level(expr)[0] is None
    )


def _owner_or_scope(expr: str | None, owner: str) -> bool:
    """`tenant AND (<owner> = app.user_id OR scope)`, as Postgres prints it."""
    if expr is None:
        return False
    operator, parts = _top_level(expr)
    if operator != "AND" or len(parts) != 2:
        return False
    tenant = [p for p in parts if _tenant_alone(p)]
    rest = [p for p in parts if not _tenant_alone(p)]
    if len(tenant) != 1 or len(rest) != 1:
        return False
    either, arms = _top_level(rest[0])
    if either != "OR" or len(arms) != 2:
        return False
    person = [a for a in arms if a.lstrip("( ").startswith(f"{owner} = ") and _USER_SETTING in a]
    scope = [a for a in arms if _SCOPE_SETTING in a and "'tenant'" in a and _USER_SETTING not in a]
    return len(person) == 1 and len(scope) == 1


def private_table_violations(
    policies: Sequence[sa.Row[Any]], listed: dict[tuple[str, str], tuple[str, str]]
) -> list[str]:
    by_table: dict[tuple[str, str], list[sa.Row[Any]]] = {}
    for r in policies:
        by_table.setdefault((r.schemaname, r.tablename), []).append(r)
    found: list[str] = []
    for (schema, table), (owner, reason) in sorted(listed.items()):
        rows = by_table.get((schema, table), [])
        if not reason.strip():
            found.append(f"{schema}.{table} is listed without a reason")
        permissive = sorted(r.policyname for r in rows if r.permissive == "PERMISSIVE")
        tenant = [r for r in rows if r.policyname == f"tenant_isolation_{table}"]
        if permissive != [f"tenant_isolation_{table}"] or not _tenant_alone(tenant[0].qual or ""):
            found.append(f"{schema}.{table}: PERMISSIVE {permissive}, not its tenant policy alone")
        restrictive = [r for r in rows if r.permissive == "RESTRICTIVE"]
        if not (
            len(restrictive) == 1
            and restrictive[0].cmd == "ALL"
            and _owner_or_scope(restrictive[0].qual, owner)
        ):
            found.append(f"{schema}.{table}: no single RESTRICTIVE `tenant AND ({owner} OR scope)`")
    for (schema, table), rows in sorted(by_table.items()):
        if (schema, table) in listed:
            continue
        if any(
            r.permissive == "RESTRICTIVE" and _USER_SETTING in f"{r.qual} {r.with_check}"
            for r in rows
        ):
            found.append(f"{schema}.{table} narrows by app.user_id and is not listed")
    return found


async def test_a_table_private_to_one_person_has_exactly_its_two_policies(
    session: AsyncSession,
) -> None:
    rows = (await session.execute(_POLICY_KINDS, {"schemas": await tenant_schemas(session)})).all()
    assert private_table_violations(rows, _PRIVATE_TO_ONE_PERSON) == []


async def test_the_private_table_rule_names_each_wrong_shape(session: AsyncSession) -> None:
    """Each shape made and rolled back in one transaction: the right one, its
    RESTRICTIVE policy made PERMISSIVE, dropped, joined by a second PERMISSIVE
    policy, narrowed by the owner alone, and an unlisted private table."""
    user = "(SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)"
    tenant = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    scope = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"
    shape = f"{tenant} AND (owner_id = {user} OR {scope})"
    probes: dict[str, tuple[str, str] | None] = {
        "right": ("AS RESTRICTIVE", shape),
        "permissive": ("AS PERMISSIVE", shape),
        "dropped": None,
        "extra": ("AS RESTRICTIVE", shape),
        "owner_only": ("AS RESTRICTIVE", f"{tenant} AND owner_id = {user}"),
        "unlisted": ("AS RESTRICTIVE", shape),
    }
    try:
        for name, policy in probes.items():
            table = f"public.private_{name}"
            await session.execute(sa.text(f"CREATE TABLE {table} (tenant_id uuid, owner_id uuid)"))
            await session.execute(
                sa.text(
                    f"CREATE POLICY tenant_isolation_private_{name} ON {table} USING ({tenant})"
                )
            )
            if policy is not None:
                kind, using = policy
                await session.execute(
                    sa.text(f"CREATE POLICY own_row ON {table} {kind} USING ({using})")
                )
        await session.execute(
            sa.text(f"CREATE POLICY wide_open ON public.private_extra USING ({tenant})")
        )
        rows = (await session.execute(_POLICY_KINDS, {"schemas": ["public"]})).all()
    finally:
        await session.rollback()
    listed = {
        ("public", f"private_{name}"): ("owner_id", "probe")
        for name in probes
        if name != "unlisted"
    }
    found = private_table_violations(
        [r for r in rows if r.tablename.startswith("private_")], listed
    )
    assert sorted(found) == [
        "public.private_dropped: no single RESTRICTIVE `tenant AND (owner_id OR scope)`",
        "public.private_extra: PERMISSIVE ['tenant_isolation_private_extra', 'wide_open'],"
        " not its tenant policy alone",
        "public.private_owner_only: no single RESTRICTIVE `tenant AND (owner_id OR scope)`",
        "public.private_permissive: PERMISSIVE ['own_row', 'tenant_isolation_private_permissive'],"
        " not its tenant policy alone",
        "public.private_permissive: no single RESTRICTIVE `tenant AND (owner_id OR scope)`",
        "public.private_unlisted narrows by app.user_id and is not listed",
    ]


# ---------------------------------------------------------------------------
# Record tables (record-access ticket 03; ADR-0105 decision 1; CLAUDE.md,
# Tenancy and authorization): every table with an `access_key` column, and each
# partition of one, read from the catalog, carries exactly the RESTRICTIVE
# `tenant_isolation_<t>` and the PERMISSIVE `record_access_<t>_select`,
# `_insert`, `_update`, `_delete`, each `tenant AND (scope OR (actor_ok AND
# reach))`, `<t>` the parent's name on a partition. Every function those
# policies depend on (`pg_depend`) is STABLE, SECURITY INVOKER, with a fixed
# `search_path`: a check that reads policy text cannot see narrowing inside a
# function (failure-modes #0). The text itself is compared with the template
# module in `dw_studio`'s `test_record_policies.py`; this file imports no context.
# ---------------------------------------------------------------------------

_RECORD_TABLES = sa.text(
    """
    SELECT n.nspname AS schema, c.relname AS name,
           coalesce((SELECT p.relname FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhparent
                     WHERE i.inhrelid = c.oid), c.relname) AS short
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND NOT starts_with(n.nspname, 'pg_')
      AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                  AND a.attname = 'access_key' AND NOT a.attisdropped)
    ORDER BY 1, 2
    """
)

_RECORD_POLICY_FUNCTIONS = sa.text(
    """
    SELECT DISTINCT p.oid::regprocedure::text AS function, p.provolatile::text AS volatility,
           p.prosecdef AS definer,
           EXISTS (SELECT 1 FROM unnest(coalesce(p.proconfig, '{}')) s
                   WHERE s LIKE 'search_path=%') AS fixed_path
    FROM pg_policy pol
    JOIN pg_depend d ON d.classid = 'pg_policy'::regclass AND d.objid = pol.oid
     AND d.refclassid = 'pg_proc'::regclass
    JOIN pg_proc p ON p.oid = d.refobjid
    WHERE EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = pol.polrelid
                  AND a.attname = 'access_key' AND NOT a.attisdropped)
    ORDER BY 1
    """
)

# Which clauses each record command's policy carries: (cmd, USING, WITH CHECK).
_RECORD_COMMANDS = {
    "select": ("SELECT", True, False),
    "insert": ("INSERT", False, True),
    "update": ("UPDATE", True, True),
    "delete": ("DELETE", True, False),
}


def _record_reach(expr: str | None) -> bool:
    """`tenant AND (scope OR (actor_ok AND ...))`, as Postgres prints it."""
    if expr is None:
        return False
    operator, parts = _top_level(expr)
    if operator != "AND" or len(parts) != 2:
        return False
    tenant = [p for p in parts if _tenant_alone(p)]
    rest = [p for p in parts if not _tenant_alone(p)]
    if len(tenant) != 1 or len(rest) != 1:
        return False
    either, arms = _top_level(rest[0])
    if either != "OR" or len(arms) != 2:
        return False
    scope = [
        a
        for a in arms
        if _SCOPE_SETTING in a and "'tenant'" in a and not any(s in a for s in _REACH_READS)
    ]
    actor = [
        a
        for a in arms
        if _top_level(a)[0] == "AND"
        and "studio.acl_actor_kind()" in _top_level(a)[1][0]
        and _SCOPE_SETTING not in a
    ]
    return len(scope) == 1 and len(actor) == 1


def record_template_violations(
    tables: Sequence[sa.Row[Any]], policies: Sequence[sa.Row[Any]]
) -> list[str]:
    by_table: dict[tuple[str, str], list[sa.Row[Any]]] = {}
    for r in policies:
        by_table.setdefault((r.schemaname, r.tablename), []).append(r)
    found: list[str] = []
    for t in tables:
        rows = {r.policyname: r for r in by_table.get((t.schema, t.name), [])}
        where = f"{t.schema}.{t.name}"
        tenant_name = f"tenant_isolation_{t.short}"
        want = {tenant_name, *(f"record_access_{t.short}_{c}" for c in _RECORD_COMMANDS)}
        if set(rows) != want:
            found.append(f"{where}: policies {sorted(rows)} are not the record set")
        tenant = rows.get(tenant_name)
        if tenant is not None and not (
            tenant.permissive == "RESTRICTIVE"
            and tenant.cmd == "ALL"
            and _tenant_alone(tenant.qual or "")
            and _tenant_alone(tenant.with_check or "")
        ):
            found.append(f"{where}: {tenant_name} is not a RESTRICTIVE tenant policy alone")
        for command, (cmd, using, check) in _RECORD_COMMANDS.items():
            policy = rows.get(f"record_access_{t.short}_{command}")
            if policy is None:
                continue
            shaped = (
                policy.permissive == "PERMISSIVE"
                and policy.cmd == cmd
                and (_record_reach(policy.qual) if using else policy.qual is None)
                and (_record_reach(policy.with_check) if check else policy.with_check is None)
            )
            if not shaped:
                found.append(f"{where}: {policy.policyname} is not `tenant AND (scope OR reach)`")
    return found


def record_function_violations(functions: Sequence[sa.Row[Any]]) -> list[str]:
    found: list[str] = []
    for f in functions:
        if f.volatility != "s":
            found.append(f"{f.function} is not STABLE")
        if f.definer:
            found.append(f"{f.function} is SECURITY DEFINER")
        if not f.fixed_path:
            found.append(f"{f.function} has no fixed search_path")
    return found


async def test_every_record_table_holds_exactly_the_record_policy_set(
    session: AsyncSession,
) -> None:
    tables = (await session.execute(_RECORD_TABLES)).all()
    assert {(t.schema, t.name) for t in tables} >= {
        ("studio", "records"),
        *(("studio", f"records_p{n}") for n in range(4)),
    }
    schemas = sorted({t.schema for t in tables})
    rows = (await session.execute(_POLICY_KINDS, {"schemas": schemas})).all()
    assert record_template_violations(tables, rows) == []


async def test_every_function_a_record_policy_reads_is_stable_invoker_and_pinned(
    session: AsyncSession,
) -> None:
    functions = (await session.execute(_RECORD_POLICY_FUNCTIONS)).all()
    assert {f.function for f in functions} >= {
        "studio.acl_actor_kind()",
        "studio.acl_user()",
        "studio.acl_objects(text,text)",
        "studio.acl_keys(text)",
        "studio.acl_create_own_keys()",
    }
    assert record_function_violations(functions) == []


_R_TENANT = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
_R_SCOPE = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"
_R_ACTOR = "(SELECT studio.acl_actor_kind()) = 'user'"


def _r_reach(function: str = "studio.acl_objects('read', 'tenant')") -> str:
    return (
        f"({_R_TENANT}) AND ({_R_SCOPE} OR ({_R_ACTOR}"
        f" AND object_id = ANY ((SELECT {function})::uuid[])))"
    )


def _r_policies(table: str, *, restrictive: bool = True, reach: str | None = None) -> list[str]:
    kind = " AS RESTRICTIVE" if restrictive else ""
    return [
        f"CREATE POLICY tenant_isolation_{table} ON public.{table}{kind}"
        f" USING ({_R_TENANT}) WITH CHECK ({_R_TENANT})",
        f"CREATE POLICY record_access_{table}_select ON public.{table} FOR SELECT"
        f" USING ({reach or _r_reach()})",
        f"CREATE POLICY record_access_{table}_insert ON public.{table} FOR INSERT"
        f" WITH CHECK ({_r_reach()})",
        f"CREATE POLICY record_access_{table}_update ON public.{table} FOR UPDATE"
        f" USING ({_r_reach()}) WITH CHECK ({_r_reach()})",
        f"CREATE POLICY record_access_{table}_delete ON public.{table} FOR DELETE"
        f" USING ({_r_reach()})",
    ]


async def test_the_record_rules_name_each_wrong_shape(session: AsyncSession) -> None:
    """Probe tables, made and rolled back as the scope rules' probes are: the
    right set; an extra tenant-only PERMISSIVE policy; `tenant_isolation_<t>`
    made PERMISSIVE; reach read through a VOLATILE, a SECURITY DEFINER and an
    unpinned `studio.acl_*` function."""
    columns = "(tenant_id uuid, object_id uuid, owner_id uuid, access_key uuid)"
    probes: dict[str, list[str]] = {
        "rec_right": _r_policies("rec_right"),
        "rec_extra": [
            *_r_policies("rec_extra"),
            f"CREATE POLICY wide_open ON public.rec_extra USING ({_R_TENANT})",
        ],
        "rec_permissive": _r_policies("rec_permissive", restrictive=False),
        "rec_volatile": _r_policies("rec_volatile", reach=_r_reach("studio.acl_probe_volatile()")),
        "rec_definer": _r_policies("rec_definer", reach=_r_reach("studio.acl_probe_definer()")),
        "rec_unpinned": _r_policies("rec_unpinned", reach=_r_reach("studio.acl_probe_unpinned()")),
    }
    functions = (
        "CREATE FUNCTION studio.acl_probe_volatile() RETURNS uuid[] LANGUAGE sql VOLATILE"
        " SET search_path = pg_catalog AS $$ SELECT '{}'::uuid[] $$",
        "CREATE FUNCTION studio.acl_probe_definer() RETURNS uuid[] LANGUAGE sql STABLE"
        " SECURITY DEFINER SET search_path = pg_catalog AS $$ SELECT '{}'::uuid[] $$",
        "CREATE FUNCTION studio.acl_probe_unpinned() RETURNS uuid[] LANGUAGE sql STABLE"
        " AS $$ SELECT '{}'::uuid[] $$",
    )
    try:
        for statement in functions:
            await session.execute(sa.text(statement))
        for table, policies in probes.items():
            await session.execute(sa.text(f"CREATE TABLE public.{table} {columns}"))
            for statement in policies:
                await session.execute(sa.text(statement))
        tables = [
            t for t in (await session.execute(_RECORD_TABLES)).all() if t.name.startswith("rec_")
        ]
        rows = (await session.execute(_POLICY_KINDS, {"schemas": ["public"]})).all()
        found = record_template_violations(tables, rows)
        reads = record_function_violations(
            [
                f
                for f in (await session.execute(_RECORD_POLICY_FUNCTIONS)).all()
                if "acl_probe" in f.function
            ]
        )
    finally:
        await session.rollback()
    assert sorted(found) == [
        "public.rec_extra: policies ['record_access_rec_extra_delete',"
        " 'record_access_rec_extra_insert', 'record_access_rec_extra_select',"
        " 'record_access_rec_extra_update', 'tenant_isolation_rec_extra', 'wide_open']"
        " are not the record set",
        "public.rec_permissive: tenant_isolation_rec_permissive is not a RESTRICTIVE tenant"
        " policy alone",
    ]
    assert sorted(reads) == [
        "studio.acl_probe_definer() is SECURITY DEFINER",
        "studio.acl_probe_unpinned() has no fixed search_path",
        "studio.acl_probe_volatile() is not STABLE",
    ]


# DO-13.2 and the read-back of each policy, under `dw_app`: a record policy made
# broken would pass every rule above and admit nothing.


async def _record_company(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A company whose one member holds `tenant_owner`, an object and two of its
    records, as the migrator; returns (tenant, owner, object)."""
    tenant = await plant_tenant(session)
    owner = await plant_person(session, tenant.tenant_id)
    membership = await plant_membership(session, tenant.tenant_id, tenant.main, owner)
    owner_role = await role_id(session, tenant.tenant_id, "tenant_owner")
    await assign(session, tenant.tenant_id, tenant.main, membership, owner_role)
    obj = (await plant_object(session, tenant, "lead", {})).object_id
    await session.execute(
        sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.tenant_id)}
    )
    for n in range(2):
        await session.execute(
            sa.text(
                "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
                " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :t, :o, :w,"
                " 'user', :u, :n, :u, :u)"
            ),
            {"t": tenant.tenant_id, "o": obj, "w": tenant.main, "u": owner, "n": f"Mẫu {n}"},
        )
    return tenant.tenant_id, owner, obj


async def test_each_record_policy_admits_a_row_and_the_tenant_scope_stays_in_its_tenant(
    db_urls: DatabaseUrls, session: AsyncSession
) -> None:
    a_tenant, a_owner, a_object = await _record_company(session)
    b_tenant, _, _ = await _record_company(session)
    await session.commit()
    workspace = await session.scalar(
        sa.text("SELECT id FROM platform.workspaces WHERE tenant_id = :t"), {"t": a_tenant}
    )
    registry = TenantWideScopeRegistry(TenantWideLane("offboarding", "probe", True))
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await bind_tenant(conn, TenantScope(tenant_id=a_tenant, principal_id=a_owner))
            await bind_actor(conn, "user")
            await conn.execute(sa.text("SELECT studio.ensure_principal_scope()"))
            read = await conn.scalar(sa.text("SELECT count(*) FROM studio.records"))
            made = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id,"
                        " owner_kind, owner_id, name, created_by, updated_by) VALUES"
                        " (gen_random_uuid(), :t, :o, :w, 'user', :u, 'Mới', :u, :u)"
                    ),
                    {"t": a_tenant, "o": a_object, "w": workspace, "u": a_owner},
                )
            ).rowcount
            updated = (
                await conn.execute(sa.text("UPDATE studio.records SET name = 'Sửa'"))
            ).rowcount
            deleted = (
                await conn.execute(sa.text("DELETE FROM studio.records WHERE name = 'Sửa'"))
            ).rowcount
            await conn.rollback()
        async with engine.connect() as conn:
            await tenant_wide_scope(conn, a_tenant, "offboarding", registry)
            seen = (
                await conn.execute(
                    sa.text("SELECT tenant_id, count(*) FROM studio.records GROUP BY 1")
                )
            ).all()
            await conn.rollback()
    finally:
        await engine.dispose()
    assert (read, made, updated, deleted) == (2, 1, 3, 3)
    assert [tuple(r) for r in seen] == [(a_tenant, 2)]
    assert b_tenant != a_tenant


async def test_reach_reads_sit_beside_a_tenant_clause_and_narrow_studio_tables(
    session: AsyncSession,
) -> None:
    """record-access ticket 03, (q): a policy reading a `studio.acl_*` reader
    or the principal outside `tenant AND (...)` is named; a `studio` table
    narrowed by either with no policy reading the scope is named; a `platform`
    table narrowed by the principal keeps the workspace rule alone."""
    tenant = "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    user = "owner_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)"
    scope = "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'"
    reach = "object_id = ANY ((SELECT studio.acl_objects('read', 'tenant'))::uuid[])"
    shapes = {
        "studio.reach_ok": f"({tenant}) AND ({scope} OR {reach})",
        "studio.reach_or": f"({tenant}) OR {reach}",
        "studio.reach_alone": reach,
        "studio.reach_blind": f"({tenant}) AND {user}",
        "platform.reach_user": f"({tenant}) AND {user}",
    }
    try:
        for table, using in shapes.items():
            await session.execute(
                sa.text(f"CREATE TABLE {table} (tenant_id uuid, object_id uuid, owner_id uuid)")
            )
            await session.execute(sa.text(f"CREATE POLICY probe ON {table} USING ({using})"))
        rows = [
            r
            for r in (await session.execute(_POLICIES, {"schemas": ["studio", "platform"]})).all()
            if r.tablename.startswith("reach_")
        ]
    finally:
        await session.rollback()
    assert sorted(scope_outside_a_tenant_clause(rows)) == [
        "studio.reach_alone.probe",
        "studio.reach_or.probe",
    ]
    assert workspace_tables_blind_to_scope(rows) == [
        "studio.reach_alone",
        "studio.reach_blind",
        "studio.reach_or",
    ]
