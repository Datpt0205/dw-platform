"""`RecordService.query` on PostgreSQL (custom-objects ticket 04; R3.3, R3.4,
R4.3, R8.1-R8.5, R8.8).

The list a workflow step and an agent's tool reach as well as the route:
the caller's `QuerySchema` built in the service's transaction, the query
parsed by `dw_kernel.filters` before any record SQL, the page read under the
record policies. The HTTP half (the two routes, `GET`'s refusals, problem+json
pointers, the cursor across pages and `count`) is
`apps/api/tests/integration/test_studio_record_lists.py`'s; the plans are
`test_record_query_plan_shape.py`'s.

"No record SQL ran" is read off the statements the app engine sent while the
call ran (`plan_shape.capture`): none names `studio.records`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from plan_shape import Captured, capture
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_kernel.errors import NotFoundError, PermissionDeniedError
from dw_kernel.filters import ListQuery, QueryError, QuerySchema, ReasonCode, parse_query
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.rate_limit import InProcessRateLimiter
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.core.adapters.field_security_inputs import SqlFieldSecurityInputs
from dw_studio.core.application.field_access import FieldAccessService
from dw_studio.records.adapters.definition_store import SqlObjectDefinitionReader
from dw_studio.records.adapters.record_store import SqlRecordStore
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.record_views import RecordPage
from dw_studio.records.application.schema_projector import ObjectSchemaProjector
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.record_world import (
    holder,
    person_door,
    publish_object,
    sessions_of,
)
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

LEAD = "co_lead"
ONLY_A = "co_only_a"
TALLY = "co_tally"
EVERY = dict.fromkeys(("read", "create", "update", "delete"), "workspace")
EDIT = dict.fromkeys(("name", "phone", "city", "amount", "stage", "note"), "edit")


def lead_document(**over: Any) -> dict[str, Any]:
    return object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("city", indexed=True),
        object_field("amount", "currency", scale=2, indexed=True),
        object_field("score", "number", number_mode="float", indexed=True),
        object_field("born", "date", indexed=True),
        object_field("seen", "datetime", indexed=True),
        object_field("vip", "boolean", indexed=True),
        object_field(
            "stage",
            "picklist",
            indexed=True,
            options=[
                {"key": "moi", "labels": {"vi": "Mới"}, "position": 0},
                {"key": "cu", "labels": {"vi": "Cũ"}, "position": 1, "active": False},
            ],
        ),
        object_field("note"),
        **over,
    )


@dataclass
class World:
    a: PlantedTenant
    b: PlantedTenant
    objects: dict[tuple[uuid.UUID, str], uuid.UUID]
    sessions: async_sessionmaker[AsyncSession]
    migrator: AsyncEngine
    app: AsyncEngine
    service: RecordService

    async def person(
        self,
        actions: dict[str, str] | None = None,
        fields: dict[str, str] | None = None,
        *,
        tenant: PlantedTenant | None = None,
        api_name: str = LEAD,
        workspace: uuid.UUID | None = None,
    ) -> Person:
        tenant = tenant or self.a
        async with self.migrator.begin() as conn:
            return await holder(
                conn,
                tenant,
                self.objects[(tenant.tenant_id, api_name)],
                EVERY if actions is None else actions,
                EDIT if fields is None else fields,
                workspace=workspace,
            )

    def door(self, person: Person) -> RecordDoor:
        return person_door(self.sessions, person)

    async def make(
        self, person: Person, name: str, api_name: str = LEAD, **fields: Any
    ) -> uuid.UUID:
        made = await self.service.create(
            self.door(person), api_name, {"name": name, "fields": fields}
        )
        return made.record.id

    async def query(
        self, person: Person, api_name: str = LEAD, *, count: bool = False, **kw: Any
    ) -> RecordPage:
        return await self.service.query(
            self.door(person), api_name, ask(person, api_name, **kw), count=count
        )


def ask(person: Person, api_name: str = LEAD, **kw: Any) -> Callable[[QuerySchema], ListQuery]:
    """What a door hands the service: the kernel's parser, bound to the caller."""

    def parse(schema: QuerySchema) -> ListQuery:
        return parse_query(
            schema,
            route=f"/studio/objects/{api_name}/records",
            tenant=person.tenant_id,
            workspace=person.workspace_id,
            limit=kw.pop("limit", 50),
            **kw,
        )

    return parse


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(studio_db: DatabaseUrls) -> AsyncIterator[World]:
    migrator = create_async_engine(studio_db.migrator, poolclass=NullPool)
    app = create_async_engine(studio_db.app, poolclass=NullPool)
    sessions = sessions_of(app)
    async with migrator.begin() as conn:
        a = await plant_tenant(conn, workspaces=2)
        b = await plant_tenant(conn)
        manager_a, manager_b = await plant_manager(conn, a), await plant_manager(conn, b)
    objects = {
        (a.tenant_id, LEAD): await publish_object(sessions, manager_a, LEAD, lead_document()),
        (b.tenant_id, LEAD): await publish_object(sessions, manager_b, LEAD, lead_document()),
        (a.tenant_id, ONLY_A): await publish_object(sessions, manager_a, ONLY_A, lead_document()),
        (a.tenant_id, TALLY): await publish_object(sessions, manager_a, TALLY, lead_document()),
    }
    service = RecordService(
        SqlRecordStore(),
        FieldAccessService(SqlFieldSecurityInputs()),
        InProcessRateLimiter(1, SystemClock()),
        ObjectSchemaProjector(SqlObjectDefinitionReader(sessions)),
        SystemClock(),
        Uuid7Generator(),
    )
    yield World(a, b, objects, sessions, migrator, app, service)
    await app.dispose()
    await migrator.dispose()


async def slot_of(conn: AsyncConnection, object_id: uuid.UUID, api_name: str) -> str:
    found = await conn.scalar(
        sa.text("SELECT slot FROM studio.field_defs WHERE object_id = :o AND api_name = :n"),
        {"o": object_id, "n": api_name},
    )
    assert isinstance(found, str)
    return found


def record_sql(captured: list[Captured]) -> list[str]:
    return [c.statement for c in captured if "studio.records" in c.statement]


def refusal(raised: pytest.ExceptionInfo[QueryError]) -> tuple[ReasonCode, str | None, str | None]:
    (problem,) = raised.value.problems
    return problem.code, problem.pointer, problem.parameter


# ---- R8.1: the live records, newest first -------------------------------------------


async def test_r8_1_the_list_is_the_live_records_newest_first(world: World) -> None:
    person = await world.person(api_name=ONLY_A)
    first = await world.make(person, "Một", ONLY_A)
    second = await world.make(person, "Hai", ONLY_A)
    gone = await world.make(person, "Đã xóa", ONLY_A)
    await world.service.delete(world.door(person), ONLY_A, gone, expected=1)

    page = await world.query(person, ONLY_A, filter={"name": {"$in": ["Một", "Hai", "Đã xóa"]}})

    assert [item.id for item in page.items] == [second, first]
    assert page.next_cursor is None and page.count is None
    # Each item is GET's shape: `hidden_fields` and only readable values.
    assert page.items[0].hidden_fields == () and "phone" in page.items[0].fields


async def test_r8_1_fields_narrows_what_each_item_carries(world: World) -> None:
    person = await world.person()
    await world.make(person, "Chọn trường", city="Huế", note="ghi")
    page = await world.query(person, filter={"name": {"$eq": "Chọn trường"}}, fields="city")
    (item,) = page.items
    assert item.fields == {"city": "Huế"} and item.name == "Chọn trường"


# ---- R8.2: Vietnamese order ---------------------------------------------------------


async def test_r8_2_name_sorts_in_vietnamese_order(world: World) -> None:
    person = await world.person()
    names = ["Đạt", "Em", "Bình", "Ân", "Đức", "An", "Dũng", "Ánh"]
    for name in names:
        await world.make(person, name, city="thu_tu")

    page = await world.query(person, filter={"city": {"$eq": "thu_tu"}}, order_by="name")

    # Written out, not `sorted()`: Python's order is not Vietnamese.
    assert [item.name for item in page.items] == [
        "An",
        "Ánh",
        "Ân",
        "Bình",
        "Dũng",
        "Đạt",
        "Đức",
        "Em",
    ]


# ---- R8.4, R8.5: what the caller may name, before any SQL --------------------------


async def test_r8_4_co7_an_unknown_or_hidden_field_is_not_readable_before_sql(
    world: World,
) -> None:
    # `phone` is secured (basic personal data): hidden without its read key.
    reader = await world.person({"read": "workspace"}, {"name": "read"})
    cases: list[tuple[dict[str, Any], tuple[ReasonCode, str | None, str | None]]] = [
        ({"filter": {"khong_co": {"$eq": "x"}}}, (ReasonCode.FIELD_NOT_READABLE, "", None)),
        (
            {"filter": {"$and": [{"city": {"$eq": "x"}}, {"phone": {"$eq": "0901234567"}}]}},
            (ReasonCode.FIELD_NOT_READABLE, "/$and/1", None),
        ),
        ({"order_by": "khong_co"}, (ReasonCode.FIELD_NOT_READABLE, None, "order_by")),
        ({"order_by": "phone"}, (ReasonCode.FIELD_NOT_READABLE, None, "order_by")),
        ({"fields": "khong_co"}, (ReasonCode.FIELD_NOT_READABLE, None, "fields")),
        ({"fields": "city,phone"}, (ReasonCode.FIELD_NOT_READABLE, None, "fields")),
    ]
    for kw, expected in cases:
        with capture(world.app) as captured, pytest.raises(QueryError) as raised:
            await world.query(reader, **kw)
        assert refusal(raised) == expected, kw
        assert record_sql(captured) == [], kw


async def test_r8_4_a_hidden_name_does_not_sort(world: World) -> None:
    blind = await world.person({"read": "workspace"}, {"city": "read"})
    with pytest.raises(QueryError) as raised:
        await world.query(blind, order_by="name")
    assert refusal(raised) == (ReasonCode.FIELD_NOT_READABLE, None, "order_by")


async def test_r8_5_a_readable_field_in_data_does_not_filter(world: World) -> None:
    person = await world.person()
    with pytest.raises(QueryError) as raised:
        await world.query(person, filter={"$or": [{"city": {"$eq": "a"}}, {"note": {"$eq": "a"}}]})
    assert refusal(raised) == (ReasonCode.FIELD_NOT_FILTERABLE, "/$or/1", None)
    with pytest.raises(QueryError) as raised:
        await world.query(person, order_by="city")
    assert refusal(raised) == (ReasonCode.FIELD_NOT_FILTERABLE, None, "order_by")


async def test_r8_6_null_and_ne_are_not_allowed(world: World) -> None:
    person = await world.person()
    for tree, pointer in (
        ({"city": {"$ne": "a"}}, ""),
        ({"city": {"$eq": None}}, "/city/$eq"),
        ({"city": {"$in": ["a", None]}}, "/city/$in/1"),
        ({"$not": {"city": {"$eq": "a"}}}, ""),
    ):
        with pytest.raises(QueryError) as raised:
            await world.query(person, filter=tree)
        assert refusal(raised) == (ReasonCode.OPERATOR_NOT_ALLOWED, pointer, None), tree


# ---- R8.1, gate (f): values through the write's coercion ----------------------------


async def test_r8_1_a_filter_value_is_coerced_as_a_write_is(world: World) -> None:
    person = await world.person()
    lead = await world.make(person, "Số chuẩn", phone="+84901234567", amount="1000.50")
    below = await world.make(person, "Ít hơn", amount="1000.49", city="tien")
    await world.service.update(world.door(person), LEAD, lead, {"fields": {"city": "tien"}})

    by_phone = await world.query(person, filter={"phone": {"$eq": "0901 234 567"}})
    assert [i.id for i in by_phone.items] == [lead]

    money = await world.query(
        person, filter={"$and": [{"city": {"$eq": "tien"}}, {"amount": {"$gte": "1000.50"}}]}
    )
    assert [i.id for i in money.items] == [lead] and below not in [i.id for i in money.items]

    for value, pointer in ((1000.5, "/amount/$gte"), ("1000.505", "/amount/$gte")):
        with pytest.raises(QueryError) as raised:
            await world.query(person, filter={"amount": {"$gte": value}})
        assert refusal(raised) == (ReasonCode.INVALID_TYPE, pointer, None)


async def test_an_inactive_option_and_the_system_columns_filter(world: World) -> None:
    person = await world.person(workspace=world.a.workspaces[1])
    kept = await world.make(person, "Giữ lựa chọn cũ", city="cu_loc")
    # An inactive option is refused to a write; a record may still keep it.
    async with world.migrator.begin() as conn:
        slot = await slot_of(conn, world.objects[(world.a.tenant_id, LEAD)], "stage")
        await conn.execute(
            sa.text(f"UPDATE studio.records SET {slot} = 'cu' WHERE id = :r"), {"r": kept}
        )
    found = await world.query(person, filter={"stage": {"$eq": "cu"}})
    assert [i.id for i in found.items] == [kept]
    with pytest.raises(QueryError) as raised:
        await world.query(person, filter={"stage": {"$eq": "khong_co_khoa"}})
    assert refusal(raised) == (ReasonCode.INVALID_TYPE, "/stage/$eq", None)

    mine = await world.query(
        person,
        filter={
            "$and": [
                {"owner": {"$eq": str(person.id)}},
                {"workspace": {"$in": [str(world.a.workspaces[1])]}},
                {"city": {"$eq": "cu_loc"}},
            ]
        },
    )
    assert [i.id for i in mine.items] == [kept]
    with pytest.raises(QueryError) as raised:
        await world.query(person, filter={"owner": {"$eq": "not-an-id"}})
    assert refusal(raised) == (ReasonCode.INVALID_TYPE, "/owner/$eq", None)


# ---- R3.3, R3.4, R4.3: the object, its key, the company, the reach -----------------


async def test_r3_3_another_companys_object_is_not_found_before_record_sql(world: World) -> None:
    stranger = await world.person(tenant=world.b)
    for count in (False, True):
        with capture(world.app) as captured, pytest.raises(NotFoundError):
            await world.query(stranger, ONLY_A, count=count)
        assert record_sql(captured) == []


async def test_r3_4_co8_no_read_key_is_refused_before_record_sql(world: World) -> None:
    writer = await world.person({"create": "workspace"})
    for count in (False, True):
        with capture(world.app) as captured, pytest.raises(PermissionDeniedError):
            await world.query(writer, count=count)
        assert record_sql(captured) == []


async def test_r4_3_co1_one_api_name_in_two_companies_lists_and_counts_its_own(
    world: World,
) -> None:
    in_a = await world.person()
    in_b = await world.person(tenant=world.b)
    await world.make(in_a, "Của A", city="hai_cong_ty")
    of_b = await world.make(in_b, "Của B", city="hai_cong_ty")

    page = await world.query(in_b, filter={"city": {"$eq": "hai_cong_ty"}}, count=True)

    assert [i.id for i in page.items] == [of_b]
    assert (page.count, page.count_capped) == (1, False)


async def test_r4_3_a_record_out_of_reach_is_in_neither_the_page_nor_the_count(
    world: World,
) -> None:
    mine = await world.person({"read": "own", "create": "own"})
    peer = await world.person()
    own = await world.make(mine, "Của tôi", city="tam")
    await world.make(peer, "Của đồng nghiệp", city="tam")

    narrow = await world.query(mine, filter={"city": {"$eq": "tam"}}, count=True)
    wide = await world.query(peer, filter={"city": {"$eq": "tam"}}, count=True)

    assert [i.id for i in narrow.items] == [own] and narrow.count == 1
    assert wide.count == 2


# ---- R8.8: the count's cap -----------------------------------------------------------


async def test_r8_8_count_is_exact_to_ten_thousand_then_capped(world: World) -> None:
    person = await world.person(api_name=TALLY)
    tally = world.objects[(world.a.tenant_id, TALLY)]
    async with world.migrator.begin() as conn:
        slot = await slot_of(conn, tally, "city")
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(person.tenant_id)}
        )
        await conn.execute(
            sa.text(
                "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
                f" owner_id, name, created_by, updated_by, {slot})"
                " SELECT gen_random_uuid(), :t, :o, :w, 'user', :p, 'Đếm ' || n, :p, :p, 'dem'"
                " FROM generate_series(1, 10001) AS n"
            ),
            {"t": person.tenant_id, "o": tally, "w": person.workspace_id, "p": person.id},
        )
    over = await world.query(person, TALLY, filter={"city": {"$eq": "dem"}}, count=True, limit=5)
    assert (over.count, over.count_capped) == (10_000, True) and len(over.items) == 5

    async with world.migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE studio.records SET deleted_at = now(), deleted_by = owner_id"
                " WHERE id = (SELECT id FROM studio.records WHERE object_id = :o LIMIT 1)"
            ),
            {"o": tally},
        )
    exact = await world.query(person, TALLY, filter={"city": {"$eq": "dem"}}, count=True)
    assert (exact.count, exact.count_capped) == (10_000, False)

    # A later page does not count.
    assert exact.next_cursor is not None
    later = await world.service.query(
        world.door(person),
        TALLY,
        ask(person, TALLY, filter={"city": {"$eq": "dem"}}, cursor=exact.next_cursor),
        count=True,
    )
    assert later.count is None and later.count_capped is None
