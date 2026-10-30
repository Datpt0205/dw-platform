"""Offboarding exports each row once, in keyset batches, and purges in an order
derived from the catalog (foundations-hardening R11.1-R11.8, FH30-FH36).

Every scratch table here is created by the migrator inside `platform`, given the
tenant policy and the grants a real tenant table has so the catalog discovery
finds it, and dropped in `finally`: a partitioned table with a DEFAULT partition
left behind would turn studio-skeleton's registry test red.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_platform.adapters.persistence.offboarding import (
    EXPORT_BATCH_ROWS,
    OffboardingPurgeStep,
    OffboardingPurgeSteps,
    OffboardingRefusedError,
    SqlTenantOffboarding,
)

pytestmark = pytest.mark.integration

_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


@pytest.fixture
async def engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(db_urls.app, poolclass=NullPool)
    yield created
    await created.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def admin(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The admin role on the test database: the one role here that may `SET ROLE dw_app`."""
    database = db_urls.app.rsplit("/", 1)[1]
    created = create_async_engine(
        f"{db_urls.admin.rsplit('/', 1)[0]}/{database}", poolclass=NullPool
    )
    yield created
    await created.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield created
    await created.dispose()


def _protect(name: str, *, delete: bool = True) -> list[str]:
    grants = "SELECT, INSERT, DELETE" if delete else "SELECT, INSERT"
    return [
        f"ALTER TABLE platform.{name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE platform.{name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation_{name} ON platform.{name} USING"
        f" ({_POLICY}) WITH CHECK ({_POLICY})",
        f"GRANT {grants} ON platform.{name} TO dw_app",
        # Default privileges hand dw_app every verb on a new platform table; a
        # table the lane must not delete from has it taken back explicitly.
        *([] if delete else [f"REVOKE DELETE ON platform.{name} FROM dw_app"]),
    ]


@asynccontextmanager
async def _scratch(
    migrator: AsyncEngine, statements: Sequence[str], drops: Sequence[str]
) -> AsyncIterator[None]:
    try:
        async with migrator.begin() as conn:
            for statement in statements:
                await conn.execute(sa.text(statement))
        yield
    finally:
        async with migrator.begin() as conn:
            for name in drops:
                await conn.execute(sa.text(f"DROP TABLE IF EXISTS platform.{name} CASCADE"))


async def _new_tenant(migrator: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, workspace = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            # As the lane finds it: a tenant whose offboarding has begun, which
            # a step guarding its tables checks (compliance-pdpl R5.6).
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status)"
                " VALUES (:t, :s, :s, 'offboarding')"
            ),
            {"t": tenant, "s": f"fh07-{tenant.hex[:10]}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                " VALUES (:w, :t, 'main', 'Main')"
            ),
            {"w": workspace, "t": tenant},
        )
    return tenant, workspace


async def _exported(
    offboarding: SqlTenantOffboarding, tenant: uuid.UUID
) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    async for batch in offboarding.export_rows(tenant):
        tables.setdefault(f"{batch.schema}.{batch.table}", []).extend(batch.rows)
    return tables


async def _count(migrator: AsyncEngine, table: str, tenant: uuid.UUID) -> int:
    async with migrator.connect() as conn:
        return int(
            await conn.scalar(
                sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant}
            )
            or 0
        )


async def test_a_partitioned_table_is_exported_once(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.1 (FH30). The partition is granted to dw_app here on purpose, against
    studio-skeleton's revoke: the fix must not depend on that revoke, and the
    table goes away with its grants at teardown."""
    name = f"zz_fh07_part_{uuid.uuid4().hex[:6]}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{name} (id uuid NOT NULL, tenant_id uuid NOT NULL,"
        f" created_at timestamptz NOT NULL, PRIMARY KEY (id, created_at))"
        f" PARTITION BY RANGE (created_at)",
        f"CREATE TABLE platform.{name}_2026_10 PARTITION OF platform.{name}"
        " FOR VALUES FROM ('2026-10-01') TO ('2026-11-01')",
        f"CREATE TABLE platform.{name}_default PARTITION OF platform.{name} DEFAULT",
        *_protect(name),
        *[
            s.replace(f"platform.{name}", f"platform.{name}_2026_10").replace(
                f"tenant_isolation_{name}", f"tenant_isolation_{name}_2026_10"
            )
            for s in _protect(name)
        ],
        *[
            s.replace(f"platform.{name}", f"platform.{name}_default").replace(
                f"tenant_isolation_{name}", f"tenant_isolation_{name}_default"
            )
            for s in _protect(name)
        ],
        f"INSERT INTO platform.{name} VALUES (gen_random_uuid(), '{tenant}', '2026-10-15'),"
        f" (gen_random_uuid(), '{tenant}', '2025-01-15')",
    ]
    async with _scratch(migrator, statements, [name]):
        exported = await _exported(SqlTenantOffboarding(session_factory=sessions), tenant)
    assert len(exported[f"platform.{name}"]) == 2
    assert f"platform.{name}_2026_10" not in exported
    assert f"platform.{name}_default" not in exported


async def test_an_export_reads_a_table_in_keyset_batches(
    sessions: async_sessionmaker[AsyncSession], engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R11.2: 2,500 rows arrive through three statements, none returning more than a thousand."""
    name = f"zz_fh07_rows_{uuid.uuid4().hex[:6]}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{name} (id uuid PRIMARY KEY, tenant_id"
        f" uuid NOT NULL, n int NOT NULL)",
        *_protect(name),
        f"INSERT INTO platform.{name} SELECT gen_random_uuid(), '{tenant}', g"
        f" FROM generate_series(1, 2500) g",
    ]
    reads: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        if name in statement and statement.lstrip().upper().startswith("SELECT *"):
            reads.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        async with _scratch(migrator, statements, [name]):
            sizes: list[int] = []
            async for batch in SqlTenantOffboarding(session_factory=sessions).export_rows(tenant):
                if batch.table == name:
                    sizes.append(len(batch.rows))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert sizes == [EXPORT_BATCH_ROWS, EXPORT_BATCH_ROWS, 500]
    assert len(reads) == 3


async def test_the_purge_audit_names_the_lane(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.3 (FH31): the operator's decision, carried out by the lane."""
    tenant, _ = await _new_tenant(migrator)
    operator = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenant_offboarding_requests (id, tenant_id,"
                " requested_by) VALUES (gen_random_uuid(), :t, :o)"
            ),
            {"t": tenant, "o": operator},
        )
    await SqlTenantOffboarding(session_factory=sessions).purge_rows(tenant)
    async with migrator.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT actor_id, details FROM platform.audit_events WHERE tenant_id = :t"
                    " AND action = 'tenant.offboarding.purged'"
                ),
                {"t": tenant},
            )
        ).one()
    assert row.actor_id == operator
    assert row.details == {"lane": "offboarding"}


async def test_restrict_and_no_action_edges_order_the_purge(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.4 (FH33): names sort against the edges, so only the derivation passes."""
    suffix = uuid.uuid4().hex[:6]
    parent, child, other = f"zz_fh07_a_{suffix}", f"zz_fh07_z_{suffix}", f"zz_fh07_y_{suffix}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{parent} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        f"CREATE TABLE platform.{child} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
        f" parent_id uuid NOT NULL REFERENCES platform.{parent}(id) ON DELETE RESTRICT)",
        f"CREATE TABLE platform.{other} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
        f" parent_id uuid NOT NULL REFERENCES platform.{parent}(id) ON DELETE NO ACTION)",
        f"CREATE INDEX ON platform.{child} (parent_id)",
        f"CREATE INDEX ON platform.{other} (parent_id)",
        *_protect(parent),
        *_protect(child),
        *_protect(other),
        f"INSERT INTO platform.{parent} VALUES ('{tenant}', '{tenant}')",
        f"INSERT INTO platform.{child} VALUES (gen_random_uuid(), '{tenant}', '{tenant}')",
        f"INSERT INTO platform.{other} VALUES (gen_random_uuid(), '{tenant}', '{tenant}')",
    ]
    async with _scratch(migrator, statements, [child, other, parent]):
        await SqlTenantOffboarding(session_factory=sessions).purge_rows(tenant)
        for table in (parent, child, other):
            assert await _count(migrator, f"platform.{table}", tenant) == 0


async def test_an_edge_reached_through_cascade_orders_the_cascading_step(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.4 (FH33): C loses rows only by CASCADE from A, and RESTRICTs P."""
    suffix = uuid.uuid4().hex[:6]
    source, only, target = f"zz_fh07_y_{suffix}", f"zz_fh07_c_{suffix}", f"zz_fh07_b_{suffix}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{source} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        f"CREATE TABLE platform.{target} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        f"CREATE TABLE platform.{only} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
        f" source_id uuid NOT NULL REFERENCES platform.{source}(id) ON DELETE CASCADE,"
        f" target_id uuid NOT NULL REFERENCES platform.{target}(id) ON DELETE RESTRICT)",
        *_protect(source),
        *_protect(target),
        *_protect(only, delete=False),
        f"INSERT INTO platform.{source} VALUES ('{tenant}', '{tenant}')",
        f"INSERT INTO platform.{target} VALUES ('{tenant}', '{tenant}')",
        f"INSERT INTO platform.{only} VALUES (gen_random_uuid(),"
        f" '{tenant}', '{tenant}', '{tenant}')",
    ]
    async with _scratch(migrator, statements, [only, source, target]):
        await SqlTenantOffboarding(session_factory=sessions).purge_rows(tenant)
        for table in (source, target, only):
            assert await _count(migrator, f"platform.{table}", tenant) == 0


async def test_a_cycle_refuses_before_any_delete(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.5 (FH33): nothing is deleted anywhere, and the error names both keys."""
    suffix = uuid.uuid4().hex[:6]
    left, right = f"zz_fh07_l_{suffix}", f"zz_fh07_r_{suffix}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{left} (id uuid PRIMARY KEY, tenant_id"
        f" uuid NOT NULL, right_id uuid)",
        f"CREATE TABLE platform.{right} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
        f" left_id uuid REFERENCES platform.{left}(id) ON DELETE RESTRICT)",
        f"ALTER TABLE platform.{left} ADD CONSTRAINT fk_{left}_r FOREIGN KEY (right_id)"
        f" REFERENCES platform.{right}(id) ON DELETE RESTRICT",
        *_protect(left),
        *_protect(right),
    ]
    async with _scratch(migrator, statements, [left, right]):
        workspaces_before = await _count(migrator, "platform.workspaces", tenant)
        with pytest.raises(OffboardingRefusedError) as refused:
            await SqlTenantOffboarding(session_factory=sessions).purge_rows(tenant)
        assert f"fk_{left}_r" in str(refused.value)
        assert await _count(migrator, "platform.workspaces", tenant) == workspaces_before == 1


async def test_steps_delete_only_the_offboarded_tenant(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.6 (FH35): tenant B keeps every row of every table the registry declares."""
    name = f"zz_fh07_s_{uuid.uuid4().hex[:6]}"
    mine, _ = await _new_tenant(migrator)
    theirs, _ = await _new_tenant(migrator)

    async def run(session: AsyncSession, tenant_id: uuid.UUID) -> None:
        await session.execute(
            sa.text(f"DELETE FROM platform.{name} WHERE tenant_id = :t"), {"t": tenant_id}
        )

    registry = OffboardingPurgeSteps()
    registry.register(
        OffboardingPurgeStep(
            name="test.purge_scratch", tables=frozenset({f"platform.{name}"}), run=run
        )
    )
    statements = [
        f"CREATE TABLE platform.{name} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        *_protect(name),
        f"INSERT INTO platform.{name} VALUES (gen_random_uuid(), '{mine}'),"
        f" (gen_random_uuid(), '{theirs}')",
    ]
    async with _scratch(migrator, statements, [name]):
        offboarding = SqlTenantOffboarding(session_factory=sessions, steps=registry)
        async with sessions() as session:
            tables = [f"{s}.{t}" for s, t in await offboarding._purgeable_tables(session)]
        before = {t: await _count(migrator, t, theirs) for t in tables}
        await offboarding.purge_rows(mine)
        after = {t: await _count(migrator, t, theirs) for t in tables}
        assert await _count(migrator, f"platform.{name}", mine) == 0
    assert after == before
    assert before[f"platform.{name}"] == 1


async def test_a_table_without_a_primary_key_refuses_the_export(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.7 (FH36): a bundle missing a table is never produced."""
    name = f"zz_fh07_nopk_{uuid.uuid4().hex[:6]}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{name} (id uuid, tenant_id uuid NOT NULL)",
        *_protect(name),
    ]
    async with _scratch(migrator, statements, [name]):
        with pytest.raises(OffboardingRefusedError, match=name):
            await _exported(SqlTenantOffboarding(session_factory=sessions), tenant)


async def test_a_kept_table_blocking_a_step_refuses_the_purge(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R11.7 (FH36): named before the first delete, not a raw foreign-key error halfway."""
    suffix = uuid.uuid4().hex[:6]
    parent, name = f"zz_fh07_p_{suffix}", f"zz_fh07_kept_{suffix}"
    tenant, _ = await _new_tenant(migrator)
    statements = [
        f"CREATE TABLE platform.{parent} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        f"CREATE TABLE platform.{name} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
        f" parent_id uuid NOT NULL REFERENCES platform.{parent}(id) ON DELETE RESTRICT)",
        *_protect(parent),
        *_protect(name, delete=False),
        f"INSERT INTO platform.{parent} VALUES ('{tenant}', '{tenant}')",
        f"INSERT INTO platform.{name} VALUES (gen_random_uuid(), '{tenant}', '{tenant}')",
    ]
    async with _scratch(migrator, statements, [name, parent]):
        with pytest.raises(OffboardingRefusedError, match=name):
            await SqlTenantOffboarding(session_factory=sessions).purge_rows(tenant)
        assert await _count(migrator, f"platform.{parent}", tenant) == 1
        assert await _count(migrator, "platform.workspaces", tenant) == 1


async def step_violations(
    admin: AsyncEngine, offboarding: SqlTenantOffboarding, tenant: uuid.UUID
) -> list[str]:
    """Each step of the derived order, run one at a time as dw_app under the
    tenant's setting, inside one migrator transaction rolled back at the end;
    counts are read in that same transaction, so a delete is seen at once. A
    table that loses rows without being declared by the step, or reached from
    its tables through CASCADE, is named (R11.4)."""
    found: list[str] = []
    async with admin.connect() as conn:
        transaction = await conn.begin()
        try:
            session = AsyncSession(bind=conn)
            steps = await offboarding._ordered_steps(session)
            keys = (
                await conn.execute(
                    sa.text(
                        "SELECT rn.nspname || '.' || r.relname AS referencing,"
                        " dn.nspname || '.' || d.relname AS referenced FROM pg_constraint k"
                        " JOIN pg_class r ON r.oid = k.conrelid JOIN pg_namespace rn ON"
                        " rn.oid = r.relnamespace"
                        " JOIN pg_class d ON d.oid = k.confrelid JOIN pg_namespace dn"
                        " ON dn.oid = d.relnamespace"
                        " WHERE k.contype = 'f' AND k.confdeltype = 'c'"
                    )
                )
            ).all()
            tables = sorted(
                {t for step in steps for t in step.tables} | {k.referencing for k in keys}
            )
            tables = [
                t
                for t in tables
                if await conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns WHERE"
                        " table_schema || '.' || table_name = :t"
                        " AND column_name = 'tenant_id'"
                    ),
                    {"t": t},
                )
            ]

            async def counts() -> dict[str, int]:
                return {
                    t: int(
                        await conn.scalar(
                            sa.text(f"SELECT count(*) FROM {t} WHERE tenant_id = :x"), {"x": tenant}
                        )
                        or 0
                    )
                    for t in tables
                }

            for step in steps:
                reach = set(step.tables)
                changed = True
                while changed:
                    changed = False
                    for key in keys:
                        if key.referenced in reach and key.referencing not in reach:
                            reach.add(key.referencing)
                            changed = True
                before = await counts()
                await conn.execute(sa.text("SET LOCAL ROLE dw_app"))
                await conn.execute(
                    sa.text(
                        "SELECT set_config('app.tenant_id', :t, true),"
                        " set_config('app.workspace_scope', 'tenant', true)"
                    ),
                    {"t": str(tenant)},
                )
                await step.run(session, tenant)
                await conn.execute(sa.text("RESET ROLE"))
                after = await counts()
                found += [
                    f"{step.name} deletes {table}, which it does not declare"
                    for table in tables
                    if after[table] < before[table] and table not in reach
                ]
        finally:
            await transaction.rollback()
    return found


async def test_a_step_that_deletes_an_undeclared_table_is_named(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """R11.4 (FH33): a step declaring A that also empties B is caught; declaring B too clears it.
    Named to sort first, so it runs before the default step B would otherwise get."""
    suffix = uuid.uuid4().hex[:6]
    declared, hidden = f"zz_fh07_d_{suffix}", f"zz_fh07_h_{suffix}"
    tenant, _ = await _new_tenant(migrator)

    async def run(session: AsyncSession, tenant_id: uuid.UUID) -> None:
        for table in (declared, hidden):
            await session.execute(
                sa.text(f"DELETE FROM platform.{table} WHERE tenant_id = :t"), {"t": tenant_id}
            )

    statements = [
        f"CREATE TABLE platform.{declared} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        f"CREATE TABLE platform.{hidden} (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        *_protect(declared),
        *_protect(hidden, delete=False),
        f"INSERT INTO platform.{declared} VALUES (gen_random_uuid(), '{tenant}')",
        f"INSERT INTO platform.{hidden} VALUES (gen_random_uuid(), '{tenant}')",
        f"GRANT DELETE ON platform.{hidden} TO dw_app",
    ]
    async with _scratch(migrator, statements, [declared, hidden]):
        wrong = OffboardingPurgeSteps()
        wrong.register(
            OffboardingPurgeStep("a_test.purge_wrong", frozenset({f"platform.{declared}"}), run)
        )
        right = OffboardingPurgeSteps()
        right.register(
            OffboardingPurgeStep(
                "a_test.purge_right", frozenset({f"platform.{declared}", f"platform.{hidden}"}), run
            )
        )
        named = await step_violations(admin, SqlTenantOffboarding(sessions, wrong), tenant)
        clean = await step_violations(admin, SqlTenantOffboarding(sessions, right), tenant)
    assert named == [f"a_test.purge_wrong deletes platform.{hidden}, which it does not declare"]
    assert clean == []
