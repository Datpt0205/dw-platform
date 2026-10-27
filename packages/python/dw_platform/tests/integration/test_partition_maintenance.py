"""Partition maintenance against real Postgres.

None of this can be checked without a database. Whether a partition created at
runtime carries row security, whether it carries the application's excess
privileges, whether a SECURITY DEFINER function is reachable by the role it was
not granted to — every one of those is a property of the catalog, and reading
the DDL that was supposed to set it is how two of these went wrong in the first
place.

The two that went wrong, both found by asking a running database:

- `audit_events_default` was readable across tenants (migration 0009), because
  RLS is not inherited by a partition;
- `audit_events_default` accepted UPDATE and DELETE from `dw_app`, because
  `0001_platform_grants.sql` revoked them on the PARENT and the blanket
  `GRANT ... ON ALL TABLES` one statement earlier had already given them to the
  partition. The append-only guarantee the file describes in prose was not true.

Both are now the creating function's job, so the tests below are about a
partition that did not exist when the migration ran.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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
from studio_catalog import append_only_violations, partition_violations, registry_violations
from test_rls_coverage import tenant_schemas

from dw_platform.adapters.persistence.partition_maintenance import (
    AUDIT_EVENTS,
    SqlPartitionMaintenance,
)
from dw_platform.retention_policy import (
    AuditRetention,
    ChannelDeliveryRetention,
    CheckpointRetention,
    KnowledgeRetention,
    RetentionClass,
    RetentionFragment,
    RetentionPolicy,
    RetentionTerm,
    load_retention_policy,
)

pytestmark = pytest.mark.integration

MONTHS_AHEAD = 2


@dataclass(frozen=True)
class _Clock:
    at: datetime

    def now(self) -> datetime:
        return self.at


def _policy(*, days: int | None = None, enforced: bool = True) -> RetentionPolicy:
    """A policy whose `platform.audit_events` fragment holds `days` and `enforced`."""
    return RetentionPolicy(
        schema_version="1.0",
        policy_id="retention",
        policy_version="1.8.0",
        classes={"default": RetentionClass(days=730, description="thường")},
        knowledge=KnowledgeRetention(deleted_grace_days=30, orphan_evidence_grace_days=7),
        audit=AuditRetention(months_ahead=MONTHS_AHEAD),
        checkpoints=CheckpointRetention(superseded_days=7, idle_thread_days=730),
        channel_deliveries=ChannelDeliveryRetention(pending_expiry_days=7),
        batch_limit=1000,
        stores={
            AUDIT_EVENTS: RetentionFragment(
                days=days, purger="drop_partition", enforced=enforced, description="giữ"
            )
        },
    )


@pytest.fixture
async def app_sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """As the runtime role, not the migrator.

    The migrator owns every object and holds BYPASSRLS, so a maintenance pass
    run as the migrator would prove nothing about the worker, which is the only
    thing that will ever run it.
    """
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


def _month_name(parent: str, at: datetime) -> str:
    return f"{parent}_{at:%Y_%m}"


def _add_months(at: datetime, count: int) -> datetime:
    month = at.month - 1 + count
    return at.replace(year=at.year + month // 12, month=month % 12 + 1, day=1)


async def _partitions(engine: AsyncEngine, parent: str, schema: str = "platform") -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT child.relname FROM pg_inherits i"
                " JOIN pg_class parent ON parent.oid = i.inhparent"
                " JOIN pg_class child ON child.oid = i.inhrelid"
                " JOIN pg_namespace n ON n.oid = parent.relnamespace"
                " WHERE n.nspname = :schema AND parent.relname = :parent"
            ),
            {"schema": schema, "parent": parent},
        )
        return {row[0] for row in rows}


async def _registered(engine: AsyncEngine) -> list[tuple[str, str]]:
    """The parents, from the registry the job reads rather than a constant here."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT schema_name, table_name FROM platform.time_partitioned_tables ORDER BY 1, 2"
            )
        )
        found = [(str(row[0]), str(row[1])) for row in rows]
    assert found, "the registry is empty, so every loop below would pass on nothing"
    return found


async def _make_month(
    engine: AsyncEngine, parent: str, at: datetime, schema: str = "platform"
) -> str:
    """A partition for an arbitrary month, through the same function the job uses."""
    async with engine.begin() as conn:
        made = await conn.scalar(
            sa.text("SELECT platform._ensure_one_partition(:schema, :parent, :month)"),
            {"schema": schema, "parent": parent, "month": at.date().replace(day=1)},
        )
    return made or _month_name(parent, at)


async def test_the_pass_creates_this_month_and_the_ones_ahead(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """Falling behind is not self-correcting: a month with no partition sends its
    rows to the DEFAULT one, and a default holding that month's rows then blocks
    the month's partition from ever being created."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    for schema, parent in await _registered(migrator):
        existing = await _partitions(migrator, parent, schema)
        for step in range(MONTHS_AHEAD + 1):
            assert _month_name(parent, _add_months(now, step)) in existing


async def test_a_partition_made_at_runtime_carries_row_security(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """Postgres does not inherit RLS to a partition created later, and a partition
    addressed by its own name uses its own settings. That is the cross-tenant leak
    migration 0009 had to repair by hand; a monthly job would re-open it every
    month unless creating and policing are the same statement."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    part = _month_name("audit_events", _add_months(now, MONTHS_AHEAD))
    async with migrator.connect() as conn:
        enabled, forced = (
            await conn.execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = 'platform' AND c.relname = :part"
                ),
                {"part": part},
            )
        ).one()
        policies = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM pg_policies"
                " WHERE schemaname = 'platform' AND tablename = :part"
            ),
            {"part": part},
        )
    assert enabled, f"{part} has row security off"
    # Without FORCE the owner reads straight past the policy, and the owner is
    # exactly who runs maintenance.
    assert forced, f"{part} does not force row security on its owner"
    assert policies == 1, f"{part} has {policies} policies"


async def test_a_partition_made_at_runtime_keeps_the_audit_log_append_only(
    app_sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls
) -> None:
    """The hole this replaces, proved the way it was found.

    `ALTER DEFAULT PRIVILEGES` hands every new table in `platform` SELECT,
    INSERT, UPDATE and DELETE to `dw_app`. For an audit partition the last two
    are precisely what the application must not have, and the parent's REVOKE
    does not reach a partition addressed by name.
    """
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()
    part = _month_name("audit_events", _add_months(now, MONTHS_AHEAD))

    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(f"UPDATE platform.{part} SET action = 'x'"))
            await conn.rollback()
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(f"DELETE FROM platform.{part}"))
            await conn.rollback()
            # And still readable through the parent, or the audit log stops
            # working entirely. By name the partition is not there for dw_app
            # at all any more (studio-skeleton R3.3).
            await conn.execute(sa.text("SELECT count(*) FROM platform.audit_events"))
    finally:
        await engine.dispose()


async def test_nothing_is_dropped_while_no_term_is_written(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """The shipped default. DROP PARTITION destroys a month instantly and there
    is no soft delete between the sweep and the data, so the term has to be a
    number somebody wrote rather than one this build guessed."""
    now = datetime.now(UTC)
    ancient = await _make_month(migrator, "audit_events", _add_months(now, -60))

    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    assert ancient in await _partitions(migrator, "audit_events")


async def test_a_term_drops_only_the_months_entirely_behind_it(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """A partition is dropped on its END, not its start: a month the cutoff falls
    inside still holds rows that are within their term."""
    now = datetime.now(UTC)
    old = await _make_month(migrator, "audit_events", _add_months(now, -50))
    straddling = await _make_month(migrator, "audit_events", _add_months(now, -13))
    # 13 months back, so the cutoff lands inside the month above and behind the
    # one before it.
    term = _policy(days=400)

    await SqlPartitionMaintenance(app_sessions, term, _Clock(now)).prune()

    remaining = await _partitions(migrator, "audit_events")
    assert old not in remaining
    assert straddling in remaining


async def test_the_default_partition_is_never_dropped(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """It has no range, so no cutoff can be behind it — and it is where a row
    lands when the job has fallen behind. Dropping it would delete exactly the
    rows nobody has a partition for yet."""
    now = datetime.now(UTC)
    term = _policy(days=1)

    await SqlPartitionMaintenance(app_sessions, term, _Clock(now)).prune()

    for schema, parent in await _registered(migrator):
        assert f"{parent}_default" in await _partitions(migrator, parent, schema)


async def test_only_the_bounded_functions_run_as_their_definer(
    migrator: AsyncEngine,
) -> None:
    """What keeps SECURITY DEFINER from being a way to run DDL of the caller's
    choosing: the two functions granted to `dw_app` take a bounded integer and
    two timestamps, and the one that takes a TABLE NAME is not a definer at all.

    Asserted from the catalog, because the behavioural version of this test
    passes for the wrong reason — calling the helper as `dw_app` fails with
    "permission denied for schema platform" whether or not EXECUTE was granted,
    since it runs with the caller's privileges. A mutation granting it to PUBLIC
    survived that test, which is what this one is here to catch.
    """
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT p.proname, p.prosecdef,"
                "       has_function_privilege('dw_app', p.oid, 'EXECUTE')"
                " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = 'platform' AND p.proname IN"
                "  ('_ensure_one_partition', 'ensure_time_partitions',"
                "   'drop_expired_partitions', '_revoke_all_but_owner')"
            )
        )
        privileges = {name: (definer, granted) for name, definer, granted in rows}

    assert privileges["_ensure_one_partition"] == (False, False)
    # Revokes on the relation it is given: run as its caller and executable by
    # nobody but its owner, or it is a way to strip another role's grants.
    assert privileges["_revoke_all_but_owner"] == (False, False)
    assert privileges["ensure_time_partitions"] == (True, True)
    assert privileges["drop_expired_partitions"] == (True, True)


async def test_an_absurd_months_ahead_is_refused(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The argument crosses a privilege boundary, so the function bounds it rather
    than trusting the Pydantic model on the other side of the connection."""
    async with app_sessions() as session, session.begin():
        with pytest.raises(Exception, match="months_ahead must be between"):
            await session.execute(sa.text("SELECT platform.ensure_time_partitions(:n)"), {"n": 999})


async def test_a_run_over_an_already_maintained_table_creates_nothing(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """Hourly, so most passes have nothing to do. A second pass that recreated or
    errored would make the lane's log unreadable and the failure real."""
    now = datetime.now(UTC)
    maintenance = SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now))
    await maintenance.prune()
    registered = await _registered(migrator)
    before = {table: await _partitions(migrator, table[1], table[0]) for table in registered}

    await maintenance.prune()

    for table in registered:
        assert await _partitions(migrator, table[1], table[0]) == before[table]


async def test_a_row_written_now_lands_in_a_real_partition_not_the_default(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """The whole point. While every row lands in the DEFAULT partition, audit
    retention cannot run at all — a default partition cannot be dropped."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    tenant_id, event_id = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.audit_events"
                " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
                "  resource_id, occurred_at)"
                " VALUES (:id, :t, :w, :id, 'probe', 'probe', :resource, now())"
            ),
            {"id": event_id, "t": tenant_id, "w": uuid.uuid4(), "resource": str(event_id)},
        )
        landed = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.audit_events_default WHERE id = :id"),
            {"id": event_id},
        )
        in_month = await conn.scalar(
            sa.text(
                f"SELECT count(*) FROM platform.{_month_name('audit_events', now)} WHERE id = :id"
            ),
            {"id": event_id},
        )
        await conn.execute(
            sa.text("DELETE FROM platform.audit_events WHERE id = :id"), {"id": event_id}
        )
    assert landed == 0
    assert in_month == 1


async def test_every_partition_of_the_audit_table_is_policed(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """Catalog-driven, so a partition somebody adds later is covered the day it
    exists rather than the day somebody remembers to extend this file.

    `test_privileges.py` asks the same question of the parents. Asking it only
    there is how the append-only guarantee was false for as long as it was.
    """
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT child.relname, child.relrowsecurity, child.relforcerowsecurity,"
                "       has_table_privilege('dw_app', child.oid, 'UPDATE'),"
                "       has_table_privilege('dw_app', child.oid, 'DELETE')"
                " FROM pg_inherits i"
                " JOIN pg_class parent ON parent.oid = i.inhparent"
                " JOIN pg_class child ON child.oid = i.inhrelid"
                " JOIN pg_namespace n ON n.oid = parent.relnamespace"
                " WHERE n.nspname = 'platform' AND parent.relname = :parent"
            ),
            {"parent": "audit_events"},
        )
        partitions = rows.all()

    assert partitions, "audit_events has no partitions at all"
    for name, enabled, forced, can_update, can_delete in partitions:
        assert enabled and forced, f"{name} is reachable across tenants by name"
        assert not can_update, f"{name} lets the application rewrite audit history"
        assert not can_delete, f"{name} lets the application delete audit history"


async def test_a_month_already_stranded_in_the_default_is_recovered(
    migrator: AsyncEngine,
) -> None:
    """The failure that wrote this behaviour, kept where it can happen again.

    A row for a month with no partition lands in the DEFAULT one. Postgres then
    refuses to create that month's partition — it scans the default, finds rows
    that would belong to the new range, and errors. So the state is terminal
    unless the creating function relocates them: one missed maintenance window
    and that month could never be partitioned, which also means it could never
    be dropped.

    Found by running the whole integration suite rather than this file: other
    tests write audit events first, and the pass then could not create the
    current month.
    """
    now = datetime.now(UTC)
    stranded_month = _add_months(now, -7)
    event_id, resource = uuid.uuid4(), str(uuid.uuid4())
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.audit_events"
                " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
                "  resource_id, occurred_at)"
                " VALUES (:id, :t, :w, :id, 'stranded', 'probe', :resource, :at)"
            ),
            {
                "id": event_id,
                "t": uuid.uuid4(),
                "w": uuid.uuid4(),
                "resource": resource,
                "at": stranded_month,
            },
        )
        in_default = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.audit_events_default WHERE id = :id"),
            {"id": event_id},
        )
    assert in_default == 1, "the fixture did not reproduce the stranded state"

    part = await _make_month(migrator, "audit_events", stranded_month)

    async with migrator.begin() as conn:
        moved = await conn.scalar(
            sa.text(f"SELECT count(*) FROM platform.{part} WHERE id = :id"), {"id": event_id}
        )
        left_behind = await conn.scalar(
            sa.text("SELECT count(*) FROM platform.audit_events_default WHERE id = :id"),
            {"id": event_id},
        )
        await conn.execute(
            sa.text("DELETE FROM platform.audit_events WHERE id = :id"), {"id": event_id}
        )
    assert moved == 1, "the row was not relocated into its month"
    assert left_behind == 0, "the row is in two partitions at once"
    # The default has to be BACK. Relocating means detaching it, and a parent
    # left without one rejects every row no partition covers instead of letting
    # it land safely — the recovery would have caused the outage it prevents.
    assert "audit_events_default" in await _partitions(migrator, "audit_events")
    await _writes_land(migrator, _add_months(now, -9))


async def _writes_land(engine: AsyncEngine, at: datetime) -> None:
    """A row for a month nothing covers still inserts, which is what the DEFAULT
    partition is for."""
    event_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.audit_events"
                " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
                "  resource_id, occurred_at)"
                " VALUES (:id, :t, :w, :id, 'uncovered', 'probe', :resource, :at)"
            ),
            {
                "id": event_id,
                "t": uuid.uuid4(),
                "w": uuid.uuid4(),
                "resource": str(event_id),
                "at": at,
            },
        )
        await conn.execute(
            sa.text("DELETE FROM platform.audit_events WHERE id = :id"), {"id": event_id}
        )


async def test_a_decided_term_still_drops_nothing_until_it_is_enforced(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """The state the policy file actually ships in, and it is not the same as
    having no term at all.

    `days` says what was decided; `enforced` says whether it may run. They are
    separate because DROP PARTITION is instant and irreversible, and flipping
    `enforced` must be its own deliberate act, gated on the restore procedure it
    leans on actually having run — see test_restore_drill.py, which now proves
    dump -> restore -> migrate-heads round-trips rather than leaving that as a
    written-but-untried comment.

    Partitions are still created, because creating them is what keeps next
    month's rows out of the default and carries no risk at all.
    """
    now = datetime.now(UTC)
    ancient = await _make_month(migrator, "audit_events", _add_months(now, -60))
    decided = _policy(days=1, enforced=False)

    await SqlPartitionMaintenance(app_sessions, decided, _Clock(now)).prune()

    existing = await _partitions(migrator, "audit_events")
    assert ancient in existing, "a term that is not enforced still dropped a month"
    assert _month_name("audit_events", now) in existing, "creating ahead was gated too"


# ---------------------------------------------------------------------------
# The registry (studio-skeleton R3): every registered table, in its own schema,
# partitioned the same way, and a partition nobody but its owner can reach.
# ---------------------------------------------------------------------------

_PREDICATE = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_STUDIO_PROBE = ("studio", "pm_partition_probe")
_PLATFORM_PROBE = ("platform", "pm_platform_probe")
_UNREGISTERED_PROBE = ("studio", "pm_unregistered_probe")


def _probe_ddl(schema: str, table: str) -> list[str]:
    """A range-partitioned tenant table with a policed DEFAULT partition, the
    shape a Studio spec registers."""
    default = f"{table}_default"
    return [
        f"CREATE TABLE {schema}.{table} (id uuid NOT NULL, tenant_id uuid NOT NULL,"
        f" created_at timestamptz NOT NULL, status text) PARTITION BY RANGE (created_at)",
        f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{table} ON {schema}.{table}"
        f" USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})",
        f"CREATE TABLE {schema}.{default} PARTITION OF {schema}.{table} DEFAULT",
        f"ALTER TABLE {schema}.{default} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {schema}.{default} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{default} ON {schema}.{default}"
        f" USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})",
        f"SELECT platform._revoke_all_but_owner('{schema}.{default}'::regclass)",
    ]


@pytest.fixture
async def probes(migrator: AsyncEngine) -> AsyncIterator[None]:
    """Two registered probes, one in `studio` and one in `platform`, and one
    that is not registered. Committed, because the maintenance pass runs as
    `dw_app` on its own connection; dropped in `finally`, so a failed test
    leaves nothing behind for the catalog checks of the next one."""
    try:
        async with migrator.begin() as conn:
            for schema, table in (_STUDIO_PROBE, _PLATFORM_PROBE, _UNREGISTERED_PROBE):
                for statement in _probe_ddl(schema, table):
                    await conn.execute(sa.text(statement))
            # Written through the parent: studio grants writes per table.
            await conn.execute(
                sa.text(
                    "GRANT INSERT, UPDATE (status), DELETE ON studio.pm_partition_probe TO dw_app"
                )
            )
            for schema, table in (_STUDIO_PROBE, _PLATFORM_PROBE):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.time_partitioned_tables VALUES"
                        " (:s, :t, false, 'test_partition_maintenance')"
                    ),
                    {"s": schema, "t": table},
                )
        yield
    finally:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "DELETE FROM platform.time_partitioned_tables"
                    " WHERE registered_by = 'test_partition_maintenance'"
                )
            )
            for schema, table in (_STUDIO_PROBE, _PLATFORM_PROBE, _UNREGISTERED_PROBE):
                await conn.execute(sa.text(f"DROP TABLE IF EXISTS {schema}.{table}"))


async def test_the_pass_partitions_every_registered_table_and_no_other(
    app_sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine, probes: None
) -> None:
    """R3.1: in the table's own schema, this month and `months_ahead` after it."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()

    for schema, table in (_STUDIO_PROBE, _PLATFORM_PROBE):
        existing = await _partitions(migrator, table, schema)
        for step in range(MONTHS_AHEAD + 1):
            assert _month_name(table, _add_months(now, step)) in existing, (schema, step)
    schema, table = _UNREGISTERED_PROBE
    assert await _partitions(migrator, table, schema) == {f"{table}_default"}


async def test_a_registered_partition_is_policed_and_reached_only_through_its_parent(
    app_sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    db_urls: DatabaseUrls,
    probes: None,
) -> None:
    """R3.2, R3.3, in `studio` and in `platform`."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()
    tenant = uuid.uuid4()

    for schema, table in (_STUDIO_PROBE, _PLATFORM_PROBE):
        part = _month_name(table, now)
        async with migrator.connect() as conn:
            enabled, forced, policies = (
                await conn.execute(
                    sa.text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity,"
                        " (SELECT count(*) FROM pg_policies p"
                        "  WHERE p.schemaname = :s AND p.tablename = :t"
                        "    AND p.policyname = 'tenant_isolation_' || :t)"
                        " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = :s AND c.relname = :t"
                    ),
                    {"s": schema, "t": part},
                )
            ).one()
        assert (enabled, forced, policies) == (True, True, 1), (schema, part)

        async with app_sessions() as session:
            with pytest.raises(Exception, match="permission denied"):
                await session.execute(sa.text(f"SELECT count(*) FROM {schema}.{part}"))
            await session.rollback()
            async with session.begin():
                await session.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
                )
                await session.execute(
                    sa.text(
                        f"INSERT INTO {schema}.{table} (id, tenant_id, created_at)"
                        " VALUES (gen_random_uuid(), :t, now())"
                    ),
                    {"t": tenant},
                )
                seen = await session.scalar(sa.text(f"SELECT count(*) FROM {schema}.{table}"))
                await session.execute(sa.text(f"DELETE FROM {schema}.{table}"))
        assert seen == 1, f"{schema}.{table} is not readable and writable through its parent"


async def test_row_security_holds_on_a_new_partition_for_a_role_granted_it(
    app_sessions: async_sessionmaker[AsyncSession], db_urls: DatabaseUrls, probes: None
) -> None:
    """R3.2, behaviourally: a role that WAS granted SELECT on the new partition,
    with no `app.tenant_id`, reads nothing, because the partition carries its
    own forced policy. Without ENABLE in the creating function it would read
    the row."""
    now = datetime.now(UTC)
    await SqlPartitionMaintenance(app_sessions, _policy(), _Clock(now)).prune()
    schema, table = _STUDIO_PROBE
    part = _month_name(table, now)
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            for statement in (
                "CREATE ROLE pm_probe_reader NOLOGIN NOBYPASSRLS",
                "GRANT USAGE ON SCHEMA studio TO pm_probe_reader",
                f"GRANT SELECT ON {schema}.{part} TO pm_probe_reader",
                f"INSERT INTO {schema}.{table} (id, tenant_id, created_at)"
                " VALUES (gen_random_uuid(), gen_random_uuid(), now())",
                "SET LOCAL ROLE pm_probe_reader",
            ):
                await conn.execute(sa.text(statement))
            seen = await conn.scalar(sa.text(f"SELECT count(*) FROM {schema}.{part}"))
            await conn.rollback()
    finally:
        await admin.dispose()
    assert seen == 0, "a role granted the partition read rows with no tenant set"


def _pinned_policy() -> RetentionPolicy:
    """The policy the `partitions` lane loads: the pinned file and fragment set,
    from `dw_platform.retention_policy`'s own constants."""
    return load_retention_policy()


async def test_the_registry_and_its_partitions_hold_on_the_checkout(migrator: AsyncEngine) -> None:
    """R3.4, R3.6, R3.7, R3.8 on the migrated checkout."""
    policy = _pinned_policy()
    async with migrator.connect() as conn:
        assert [v for v in await registry_violations(conn) if v.startswith("R3.4")] == []
        assert await partition_violations(conn, await tenant_schemas(conn)) == []
        assert await append_only_violations(conn, policy.term) == []


_TERM = RetentionTerm(days=30, enforced=True)


async def _planted(db_urls: DatabaseUrls, statements: list[str], check: Any) -> list[str]:
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            for statement in statements:
                await conn.execute(sa.text(statement))
            found: list[str] = await check(conn)
            await conn.rollback()
    finally:
        await admin.dispose()
    return found


async def test_an_unregistered_partitioned_table_and_a_stale_row_are_named(
    db_urls: DatabaseUrls,
) -> None:
    """R3.4, both ways."""
    found = await _planted(
        db_urls,
        [
            *_probe_ddl("studio", "pm_unlisted_probe"),
            "INSERT INTO platform.time_partitioned_tables"
            " VALUES ('studio', 'pm_gone_probe', true, 'pm-stale-probe')",
        ],
        registry_violations,
    )
    assert (
        "R3.4 studio.pm_unlisted_probe is range-partitioned with a DEFAULT partition"
        " and not registered" in found
    )
    assert (
        "R3.4 registered studio.pm_gone_probe (registered_by pm-stale-probe) is not a"
        " range-partitioned table with a DEFAULT partition" in found
    )


_PARTITION_PLANTS: dict[str, tuple[list[str], str]] = {
    "SELECT on the audit default for dw_app": (
        ["GRANT SELECT ON platform.audit_events_default TO dw_app"],
        "R3.6 dw_app holds a privilege on partition platform.audit_events_default",
    ),
    "SELECT on the audit default for dw_provisioner": (
        ["GRANT SELECT ON platform.audit_events_default TO dw_provisioner"],
        "R3.6 dw_provisioner holds a privilege on partition platform.audit_events_default",
    ),
    "a column of the audit default for dw_provisioner": (
        ["GRANT SELECT (tenant_id) ON platform.audit_events_default TO dw_provisioner"],
        "R3.6 dw_provisioner holds a privilege on partition platform.audit_events_default",
    ),
    "dw_agent_ro a member of a role holding a partition": (
        [
            "GRANT SELECT ON platform.audit_events_default TO dw_app",
            "GRANT dw_app TO dw_agent_ro",
        ],
        "R3.6 dw_agent_ro reaches partition platform.audit_events_default as a member of dw_app",
    ),
    "a studio partition outside the registry": (
        [
            "SET LOCAL ROLE dw_migrator",
            "CREATE TABLE studio.pm_list_probe (tenant_id uuid, kind text)"
            " PARTITION BY LIST (kind)",
            "CREATE TABLE studio.pm_list_probe_a PARTITION OF studio.pm_list_probe"
            " FOR VALUES IN ('a')",
            "RESET ROLE",
        ],
        "R3.6 dw_app holds a privilege on partition studio.pm_list_probe_a",
    ),
}


@pytest.mark.parametrize("case", sorted(_PARTITION_PLANTS))
async def test_each_planted_partition_grant_is_named(db_urls: DatabaseUrls, case: str) -> None:
    """R3.6 can fail: a grant on a partition, direct, per column or through
    membership, and a studio partition the registry does not know."""
    statements, expected = _PARTITION_PLANTS[case]

    async def check(conn: AsyncConnection) -> list[str]:
        return await partition_violations(conn, await tenant_schemas(conn))

    found = await _planted(db_urls, statements, check)
    assert expected in found, found


async def test_a_registered_table_without_a_term_is_named_by_key(db_urls: DatabaseUrls) -> None:
    """R3.7: and only a lookup by the table's own key catches it. Answering every
    key with the audit log's term, the planted table would pass."""
    policy = _pinned_policy()
    statements = [
        *_probe_ddl("studio", "pm_term_probe"),
        "INSERT INTO platform.time_partitioned_tables"
        " VALUES ('studio', 'pm_term_probe', true, 'pm-term-probe')",
    ]

    async def by_key(conn: AsyncConnection) -> list[str]:
        return await append_only_violations(conn, policy.term)

    async def audit_for_all(conn: AsyncConnection) -> list[str]:
        return await append_only_violations(conn, lambda key: policy.term(AUDIT_EVENTS))

    found = await _planted(db_urls, statements, by_key)
    assert "R3.7 studio.pm_term_probe (registered_by pm-term-probe) has no retention term" in found
    assert not [v for v in await _planted(db_urls, statements, audit_for_all) if "R3.7" in v]


async def test_an_append_only_flag_that_lies_is_named(db_urls: DatabaseUrls) -> None:
    """R3.8, both ways, column UPDATE counted. Every probe here has a term, so
    only R3.8 can speak."""
    policy = _pinned_policy()

    def term_of(key: str) -> RetentionTerm | None:
        return _TERM if key.startswith("studio.pm_") else policy.term(key)

    async def check(conn: AsyncConnection) -> list[str]:
        return await append_only_violations(conn, term_of)

    column_update = await _planted(
        db_urls,
        ["GRANT UPDATE (action) ON platform.audit_events TO dw_app"],
        check,
    )
    assert "R3.8 platform.audit_events is append_only but dw_app holds UPDATE or DELETE" in (
        column_update
    )
    flags = await _planted(
        db_urls,
        [
            "SET LOCAL ROLE dw_migrator",
            *_probe_ddl("studio", "pm_nowrite_probe"),
            *_probe_ddl("studio", "pm_status_probe"),
            "GRANT UPDATE (status) ON studio.pm_status_probe TO dw_app",
            "INSERT INTO platform.time_partitioned_tables VALUES"
            " ('studio', 'pm_nowrite_probe', false, 'pm-flag-probe'),"
            " ('studio', 'pm_status_probe', false, 'pm-flag-probe')",
            "RESET ROLE",
        ],
        check,
    )
    assert (
        "R3.8 studio.pm_nowrite_probe is not append_only but dw_app holds neither UPDATE"
        " nor DELETE" in flags
    )
    assert not [v for v in flags if "pm_status_probe" in v], flags


async def test_two_passes_at_once_take_turns(
    migrator: AsyncEngine, db_urls: DatabaseUrls, probes: None
) -> None:
    """R3.9: two worker replicas run the lane in the same hour, and a row of a
    month with no partition yet waits in the DEFAULT. One pass creates the month
    and moves the row; the other finds it done. Neither errors, and the row is
    moved once."""
    now = datetime.now(UTC)
    ahead = _add_months(now, 1)
    schema, table = _STUDIO_PROBE
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                f"INSERT INTO {schema}.{table} (id, tenant_id, created_at)"
                " VALUES (gen_random_uuid(), gen_random_uuid(), :at)"
            ),
            {"at": ahead},
        )

    async def one_pass() -> None:
        engine = create_async_engine(db_urls.app, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text("SELECT platform.ensure_time_partitions(:n)"), {"n": MONTHS_AHEAD}
                )
        finally:
            await engine.dispose()

    await asyncio.gather(one_pass(), one_pass())

    part = _month_name(table, ahead)
    assert part in await _partitions(migrator, table, schema)
    async with migrator.connect() as conn:
        total = await conn.scalar(sa.text(f"SELECT count(*) FROM {schema}.{table}"))
        moved = await conn.scalar(sa.text(f"SELECT count(*) FROM {schema}.{part}"))
    assert (total, moved) == (1, 1)
