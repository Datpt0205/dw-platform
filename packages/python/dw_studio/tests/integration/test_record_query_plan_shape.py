"""Every statement of a record list has an index under it, under RLS
(custom-objects ticket 04 step 6; R8.9, CO19; app-standards R6).

The statements are the real ones: `RecordService.query` runs each case as a
person of one of the four reach profiles of record-access:R9.10 (own records,
my workspace, the whole company, an object whose default access is
`public_read`), and `plan_shape.capture` keeps what it sent. Each is planned
with `EXPLAIN` as `dw_app`, bound as that person (`act_as_user`), with
`enable_seqscan = off`, and checked by `plan_shape.plan_problems`:

- every operator of every slot family and of the system columns, under each
  of the three orderings both ways: the filter's column and `object_id` in an
  Index Cond or a Recheck Cond, except through an index of the reach (`owner_id`,
  `access_key`) at the own and workspace profiles, where they may be a Filter
  over the reach set and `tenant_id` still leads the Index Cond;
- the ordering delivered by an index (`enable_sort = off`, no Sort on it) when
  there is no filter or the filter names the sort column; a filter on another
  column ordered by this one is planned with sorting priced as usual and may
  be a top-N Sort over an index scan led by `tenant_id` (gate (c), (k));
- no sequential scan of `studio.records` or a partition, anywhere.

A predicate on `data` is shown to turn the check red.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from plan_shape import (
    Captured,
    Expectation,
    admin_url_of,
    capture,
    explain,
    paged,
    plan_problems,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.filters import ListQuery, QuerySchema, parse_query
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
from dw_studio.records.adapters.record_store import SqlRecordStore
from dw_studio.records.application.record_service import RecordService
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.record_world import holder, person_door, publish_object, sessions_of
from dw_studio.testing.records import act_as_user
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

LEAD, OPEN = "plan_lead", "plan_open"
TABLE = "studio.records"
REACH_INDEXES = ("owner_id", "access_key")
COMPARE = ("$eq", "$in", "$lt", "$lte", "$gt", "$gte")
ORDERS = tuple(f"{c} {d}" for c in ("name", "created_at", "updated_at") for d in ("asc", "desc"))
# api_name -> {operator: value}: each bound selects a few rows of the seed
# (400 per owner), as a list filter does; one that matches nearly every row
# is rightly read by walking the ordering's index, which no index condition
# then carries.
FILTERS: dict[str, dict[str, Any]] = {
    "city": {"eq": "c1", "low": "c0", "high": "c9"},
    "phone": {"eq": "+84900000007", "low": "+84900000003", "high": "+84900400395"},
    "amount": {"eq": "700", "low": "300", "high": "39800"},
    "score": {"eq": 10.5, "low": 4.0, "high": 597.0},
    "born": {"eq": "2026-01-08", "low": "2026-01-02", "high": "2026-10-26"},
    "seen": {
        "eq": "2026-01-01T07:00:00+00:00",
        "low": "2026-01-01T03:00:00+00:00",
        "high": "2026-01-17T12:00:00+00:00",
    },
    "vip": {"eq": True},
    "name": {"eq": "Bản ghi 7", "low": "Bản ghi 1", "high": "Bản ghi 99"},
    "created_at": {
        "eq": "2026-05-31T23:53:00+00:00",
        "low": "2026-05-31T17:25:00+00:00",
        "high": "2026-05-31T23:56:00+00:00",
    },
    "updated_at": {
        "eq": "2026-05-31T23:53:00+00:00",
        "low": "2026-05-31T17:25:00+00:00",
        "high": "2026-05-31T23:56:00+00:00",
    },
}
BOUND = {"$eq": "eq", "$in": "eq", "$lt": "low", "$lte": "low", "$gt": "high", "$gte": "high"}
COLUMNS = {"name": "name", "created_at": "created_at", "updated_at": "updated_at"}


def document(**over: Any) -> dict[str, Any]:
    return object_document(
        object_field("city", indexed=True),
        object_field("phone", "phone", is_unique=True),
        object_field("amount", "currency", scale=0, indexed=True),
        object_field("score", "number", number_mode="float", indexed=True),
        object_field("born", "date", indexed=True),
        object_field("seen", "datetime", indexed=True),
        object_field("vip", "boolean", indexed=True),
        object_field("note"),
        **over,
    )


@dataclass
class Profile:
    label: str
    api_name: str
    person: Person
    through_reach: bool


@dataclass
class World:
    tenant: PlantedTenant
    sessions: async_sessionmaker[AsyncSession]
    app: AsyncEngine
    service: RecordService
    profiles: list[Profile]


async def seed(conn: Any, tenant: PlantedTenant, obj: uuid.UUID, owners: list[Person]) -> None:
    slots = {
        r.api_name: r.slot
        for r in await conn.execute(
            sa.text("SELECT api_name, slot FROM studio.field_defs WHERE object_id = :o"),
            {"o": obj},
        )
        if r.slot is not None
    }
    await conn.execute(
        sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.tenant_id)}
    )
    for index, owner in enumerate(owners):
        await conn.execute(
            sa.text(
                "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
                " owner_id, name, created_by, updated_by, created_at, updated_at,"
                f" {slots['city']}, {slots['phone']}, {slots['amount']}, {slots['score']},"
                f" {slots['born']}, {slots['seen']}, {slots['vip']})"
                " SELECT gen_random_uuid(), :t, :o, :w, 'user', :p, 'Bản ghi ' || n, :p, :p,"
                " timestamptz '2026-06-01' - n * interval '1 minute',"
                " timestamptz '2026-06-01' - n * interval '1 minute',"
                " 'c' || (n % 50), '+8490' || lpad((n + :k * 100000)::text, 7, '0'), n * 100,"
                " n * 1.5, date '2026-01-01' + n % 300, timestamptz '2026-01-01' + n * interval"
                " '1 hour', n % 20 = 0"
                " FROM generate_series(1, 400) AS n"
            ),
            {
                "t": tenant.tenant_id,
                "o": obj,
                "w": owner.workspace_id,
                "p": owner.id,
                "k": index,
            },
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = sessions_of(app)
    async with migrator.begin() as conn:
        tenant = await plant_tenant(conn, workspaces=2)
        manager = await plant_manager(conn, tenant)
    lead = await publish_object(sessions, manager, LEAD, document())
    opened = await publish_object(sessions, manager, OPEN, document(default_access="public_read"))
    every = dict.fromkeys(
        ("name", "city", "phone", "amount", "score", "born", "seen", "vip"), "read"
    )
    async with migrator.begin() as conn:
        own = await holder(conn, tenant, lead, {"read": "own"}, every)
        workspace = await holder(conn, tenant, lead, {"read": "workspace"}, every)
        company = await holder(conn, tenant, lead, {"read": "tenant"}, every)
        public = await holder(conn, tenant, opened, {"read": "own"}, every)
        other = await holder(
            conn, tenant, lead, {"read": "own"}, every, workspace=tenant.workspaces[1]
        )
        for obj in (lead, opened):
            await seed(conn, tenant, obj, [own, workspace, company, public, other])
        await conn.execute(sa.text("ANALYZE studio.records"))
    service = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        InProcessRateLimiter(1, SystemClock()),
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        SystemClock(),
        Uuid7Generator(),
    )
    profiles = [
        Profile("own", LEAD, own, True),
        Profile("workspace", LEAD, workspace, True),
        Profile("company", LEAD, company, False),
        Profile("public_read", OPEN, public, False),
    ]
    yield World(tenant, sessions, app, service, profiles)
    await app.dispose()
    await migrator.dispose()


@dataclass(frozen=True)
class Case:
    order_by: str
    filter: dict[str, Any] | None
    filter_column: str | None
    cursor: bool = False


async def statements_of(world: World, profile: Profile, case: Case) -> list[Captured]:
    """What the service sent for ``case``: its page, and a first page's count."""
    cursor = None
    if case.cursor:
        first = await run(world, profile, case, None)
        cursor = first.next_cursor
        assert cursor is not None, case
    with capture(world.app) as captured:
        await run(world, profile, case, cursor)
    return paged(captured, TABLE)


async def run(world: World, profile: Profile, case: Case, cursor: str | None) -> Any:
    person = profile.person

    def parse(schema: QuerySchema) -> ListQuery:
        return parse_query(
            schema,
            route=f"/studio/objects/{profile.api_name}/records",
            tenant=person.tenant_id,
            workspace=person.workspace_id,
            filter=case.filter,
            order_by=case.order_by,
            cursor=cursor,
            limit=20,
        )

    return await world.service.query(
        person_door(world.sessions, person), profile.api_name, parse, count=cursor is None
    )


async def problems(
    world: World, profile: Profile, statements: list[Captured], expected: Expectation
) -> list[str]:
    found: list[str] = []
    async with world.app.connect() as conn, conn.begin() as tx:
        await act_as_user(conn, profile.person.tenant_id, profile.person.id)
        await conn.execute(sa.text("SET LOCAL enable_seqscan = off"))
        if not expected.top_n:
            await conn.execute(sa.text("SET LOCAL enable_sort = off"))
        for statement in statements:
            plan = await explain(conn, statement)
            found.extend(
                f"{profile.label}: {p} :: {statement.statement}"
                for p in await plan_problems(conn, plan, expected)
            )
        await tx.rollback()
    return found


def expectation(
    profile: Profile, case: Case, column_of: dict[str, str], *, count: bool
) -> Expectation:
    sort_column = COLUMNS[case.order_by.split(" ")[0]]
    column = None if case.filter_column is None else column_of[case.filter_column]
    other_column = column is not None and column != sort_column
    predicates: tuple[str, ...] = ("object_id",) if column is None else ("object_id", column)
    if column == "workspace_id":
        # `(tenant_id, workspace_id)` has no `object_id`: one of the two is a
        # Filter whichever index answers (agent, theo ủy quyền 31/10/2026; if
        # wrong, ticket 07 indexes `(tenant_id, object_id, workspace_id, id)`).
        predicates = ()
    return Expectation(
        TABLE,
        predicates=predicates,
        sort_keys=() if count else (sort_column, "id"),
        reach_indexes=REACH_INDEXES if profile.through_reach else (),
        top_n=other_column and not count,
    )


async def column_map(world: World, api_name: str) -> dict[str, str]:
    async with world.app.connect() as conn, conn.begin():
        await act_as_user(conn, world.tenant.tenant_id, world.profiles[2].person.id)
        rows = await conn.execute(
            sa.text(
                "SELECT f.api_name, f.slot FROM studio.field_defs f JOIN studio.object_defs o"
                " ON o.id = f.object_id AND o.tenant_id = f.tenant_id WHERE o.api_name = :n"
            ),
            {"n": api_name},
        )
        found = {r.api_name: r.slot for r in rows if r.slot is not None}
    return {**found, **COLUMNS, "owner": "owner_id", "workspace": "workspace_id"}


def cases(profile: Profile) -> list[Case]:
    found = [Case(order, None, None) for order in ORDERS]
    found += [Case(order, None, None, cursor=True) for order in ORDERS]
    for api_name, bounds in FILTERS.items():
        operators = COMPARE if "low" in bounds else ("$eq",)
        for operator in operators:
            value = bounds[BOUND[operator]]
            operand = [value] if operator == "$in" else value
            for order in ORDERS:
                found.append(Case(order, {api_name: {operator: operand}}, api_name))
    for api_name, value in (
        ("owner", str(profile.person.id)),
        ("workspace", str(profile.person.workspace_id)),
    ):
        for operator in ("$eq", "$in"):
            operand = [value] if operator == "$in" else value
            for order in ORDERS:
                found.append(Case(order, {api_name: {operator: operand}}, api_name))
    return found


async def test_r8_9_co19_every_list_statement_has_an_index_under_rls(world: World) -> None:
    found: list[str] = []
    shapes: Counter[str] = Counter()
    planned = 0
    for profile in world.profiles:
        column_of = await column_map(world, profile.api_name)
        for case in cases(profile):
            statements = await statements_of(world, profile, case)
            assert statements, case
            page, *rest = statements
            planned += len(statements)
            seen = await problems(
                world, profile, [page], expectation(profile, case, column_of, count=False)
            )
            if rest:
                seen += await problems(
                    world, profile, rest, expectation(profile, case, column_of, count=True)
                )
            found += seen
            operator = "" if case.filter is None else next(iter(*case.filter.values()))
            shapes.update(
                f"{profile.label} {case.filter_column} {operator} by {case.order_by}:"
                f" {p.split(' :: ')[0].split(': ', 1)[1]}"
                for p in seen
            )
    summary = "\n".join(f"{n} x {shape}" for shape, n in shapes.most_common(80))
    assert found == [], f"{len(found)} problems\n{summary}\n" + "\n".join(found[:3])
    assert planned > 4 * 400


async def test_a_predicate_on_data_turns_the_check_red(world: World) -> None:
    """CO19: were the compiler to read a field from `data`, the plan check
    sees it (failure-modes #3): the predicate is in no Index Cond."""
    profile = world.profiles[2]
    statements = await statements_of(world, profile, Case("created_at desc", None, None))
    page = statements[0]
    planted = Captured(
        page.statement.replace(
            "studio.records.deleted_at IS NULL",
            "studio.records.deleted_at IS NULL AND (studio.records.data ->> '1') = 'x'",
        ),
        page.parameters,
    )
    assert planted.statement != page.statement
    expected = Expectation(TABLE, predicates=("object_id", "data"), sort_keys=("created_at", "id"))
    found = await problems(world, profile, [planted], expected)
    assert any("column data" in p for p in found), found


async def test_a_dropped_slot_index_turns_the_check_red(
    world: World, studio_db: DatabaseUrls
) -> None:
    """The matrix can fail: without the partial index on the filter's slot, the
    slot's predicate is a Filter and the check names it. Planned as `dw_app`
    after the index is dropped in a transaction that is rolled back."""
    profile = world.profiles[2]
    column_of = await column_map(world, profile.api_name)
    slot = column_of["city"]
    case = Case("created_at desc", {"city": {"$eq": "c1"}}, "city")
    page, *_ = await statements_of(world, profile, case)
    expected = expectation(profile, case, column_of, count=False)
    assert await problems(world, profile, [page], expected) == []

    admin = create_async_engine(admin_url_of(studio_db), poolclass=NullPool)
    try:
        async with admin.connect() as conn, conn.begin() as tx:
            index = await conn.scalar(
                sa.text(
                    "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
                    " WHERE i.indrelid = 'studio.records'::regclass"
                    " AND pg_get_indexdef(i.indexrelid) LIKE :p"
                ),
                {"p": f"%(tenant_id, object_id, {slot}, id)%"},
            )
            assert index is not None
            await conn.execute(sa.text(f'DROP INDEX studio."{index}"'))
            await conn.execute(sa.text("SET LOCAL ROLE dw_app"))
            await act_as_user(conn, profile.person.tenant_id, profile.person.id)
            await conn.execute(sa.text("SET LOCAL enable_seqscan = off"))
            plan = await explain(conn, page)
            found = await plan_problems(conn, plan, expected)
            await tx.rollback()
    finally:
        await admin.dispose()
    assert any(f"column {slot}" in p for p in found), found
