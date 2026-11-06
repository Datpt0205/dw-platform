"""The two record lists in the running app (custom-objects ticket 04; R3.3,
R3.4, R3.6, R4.3, R8.1, R8.3, R8.4, R8.6, R8.7).

`GET /api/v1/studio/objects/{api_name}/records` and `POST .../records/query`
answer through one `RecordService.query`; what this file shows is HTTP's
half: status, problem+json with `/filter` pointers or `errors[].parameter`,
`GET` refusing `filter` and `order_by=name` (a filter value and a name cursor
stay out of URLs, ADR-0106 decision 4), the cursor across three pages and
bound to the filter and `count`, and the page body. The service's own half
(coercion, reach, count cap) is `packages/python/dw_studio/tests/integration/
test_record_query.py`'s.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from pg_test_db import DatabaseUrls
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from dw_api.bootstrap import ApiContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.main import create_app
from dw_api.settings import ApiSettings
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.testing.rbac import PlantedTenant, plant_tenant
from dw_studio.testing.objects import object_document, object_field, plant_manager
from dw_studio.testing.record_world import holder, person_door, publish_object, sessions_of
from dw_studio.testing.world import Person

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECRET = "studio-lists-secret-0123456789abcdef01"
LEAD, ONLY_A = "ls_lead", "ls_only_a"
ALL = dict.fromkeys(("read", "create", "update", "delete"), "workspace")
EDIT = dict.fromkeys(("name", "phone", "city", "note"), "edit")


def base(api_name: str = LEAD) -> str:
    return f"/api/v1/studio/objects/{api_name}/records"


def lead_document() -> dict[str, Any]:
    return object_document(
        object_field("phone", "phone", pd_category="basic", is_unique=True),
        object_field("city", indexed=True),
        object_field("note"),
    )


@dataclass
class Api:
    client: httpx.AsyncClient
    container: ApiContainer
    migrator: AsyncEngine
    a: PlantedTenant
    b: PlantedTenant
    objects: dict[tuple[uuid.UUID, str], uuid.UUID]

    async def person(
        self,
        actions: dict[str, str] | None = None,
        fields: dict[str, str] | None = None,
        *,
        tenant: PlantedTenant | None = None,
        api_name: str = LEAD,
    ) -> Person:
        tenant = tenant or self.a
        async with self.migrator.begin() as conn:
            return await holder(
                conn,
                tenant,
                self.objects[(tenant.tenant_id, api_name)],
                ALL if actions is None else actions,
                EDIT if fields is None else fields,
            )

    async def call(self, who: Person, method: str, url: str, **kw: Any) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {DevTokenVerifier(SECRET).issue(who.subject)}",
            "X-Tenant-Id": str(who.tenant_id),
            "X-Workspace-Id": str(who.workspace_id),
        }
        return await self.client.request(method, url, headers=headers, **kw)

    async def make(self, who: Person, name: str, **fields: Any) -> str:
        made = await self.call(who, "POST", base(), json={"name": name, "fields": fields})
        assert made.status_code == 201, made.text
        return str(made.json()["id"])

    async def query(
        self, who: Person, body: dict[str, Any], api_name: str = LEAD
    ) -> httpx.Response:
        return await self.call(who, "POST", f"{base(api_name)}/query", json=body)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def api(api_db: DatabaseUrls) -> AsyncIterator[Api]:
    migrator = create_async_engine(api_db.migrator, poolclass=NullPool)
    app_engine = create_async_engine(api_db.app, poolclass=NullPool)
    sessions = sessions_of(app_engine)
    async with migrator.begin() as conn:
        a = await plant_tenant(conn)
        b = await plant_tenant(conn)
        manager_a, manager_b = await plant_manager(conn, a), await plant_manager(conn, b)
    objects = {
        (a.tenant_id, LEAD): await publish_object(sessions, manager_a, LEAD, lead_document()),
        (b.tenant_id, LEAD): await publish_object(sessions, manager_b, LEAD, lead_document()),
        (a.tenant_id, ONLY_A): await publish_object(sessions, manager_a, ONLY_A, lead_document()),
    }
    container = build_container(
        ApiSettings(profile="test", database_url=api_db.app, dev_secret=SECRET)
    )
    app = create_app(container)
    assert container.engine is not None
    try:
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                yield Api(client, container, migrator, a, b, objects)
    finally:
        await container.engine.dispose()
        await app_engine.dispose()
        await migrator.dispose()


def errors(response: httpx.Response) -> list[tuple[str, str]]:
    body = response.json()
    assert response.status_code == 422 and body["code"] == "validation_failed", response.text
    return [(e.get("pointer") or e.get("parameter") or "", e["code"]) for e in body["errors"]]


# ---- R8.1: the page ---------------------------------------------------------------


async def test_r8_1_both_forms_answer_one_page_newest_first(api: Api) -> None:
    person = await api.person()
    first = await api.make(person, "Một", city="trang")
    second = await api.make(person, "Hai", city="trang")

    listed = await api.call(person, "GET", base(), params={"limit": 200})
    queried = await api.query(person, {"filter": {"city": {"$eq": "trang"}}, "limit": 200})

    assert listed.status_code == 200 and queried.status_code == 200, queried.text
    assert listed.headers["Cache-Control"] == "private, no-store"
    ids = [item["id"] for item in queried.json()["items"]]
    assert ids == [second, first]
    assert [i["id"] for i in listed.json()["items"]][:2] == [second, first]
    body = queried.json()
    assert set(body) == {"items", "next_cursor"}
    item = body["items"][0]
    assert "permissions" not in item and item["etag"] == '"1"' and "hidden_fields" in item
    assert item["owner"] == {"kind": "user", "id": str(person.id)}


async def test_r8_1_limit_is_two_hundred_at_most(api: Api) -> None:
    person = await api.person()
    over = await api.call(person, "GET", base(), params={"limit": 201})
    assert over.status_code == 422
    assert errors(await api.query(person, {"limit": 201})) == [("limit", "limit_out_of_range")]


# ---- R8.4: what GET refuses, and what both refuse ---------------------------------


async def test_r8_4_get_takes_no_filter_and_no_name_order(api: Api) -> None:
    person = await api.person()
    tree = '{"city": {"$eq": "x"}}'
    assert errors(await api.call(person, "GET", base(), params={"filter": tree})) == [
        ("filter", "parameter_not_accepted")
    ]
    assert errors(await api.call(person, "GET", base(), params={"order_by": "name"})) == [
        ("order_by", "parameter_not_accepted")
    ]
    ordered = await api.call(person, "GET", base(), params={"order_by": "updated_at asc"})
    assert ordered.status_code == 200
    same = await api.query(person, {"filter": {"city": {"$eq": "x"}}, "order_by": "name"})
    assert same.status_code == 200, same.text


async def test_r8_4_co7_an_unknown_or_hidden_field_points_where_it_stands(api: Api) -> None:
    reader = await api.person({"read": "workspace"}, {"name": "read", "city": "read"})
    for body, expected in (
        ({"filter": {"khong_co": {"$eq": 1}}}, ("/filter", "field_not_readable")),
        (
            {"filter": {"$or": [{"city": {"$eq": "a"}}, {"phone": {"$eq": "0901234567"}}]}},
            ("/filter/$or/1", "field_not_readable"),
        ),
        ({"order_by": "phone"}, ("order_by", "field_not_readable")),
        ({"fields": "khong_co"}, ("fields", "field_not_readable")),
        ({"filter": {"note": {"$eq": "a"}}}, ("/filter", "field_not_filterable")),
    ):
        refused = await api.query(reader, body)
        assert errors(refused) == [expected], body
        # The body never repeats what was sent.
        assert "0901234567" not in refused.text and "khong_co" not in refused.text
    hidden = await api.call(reader, "GET", base(), params={"fields": "phone"})
    assert errors(hidden) == [("fields", "field_not_readable")]


# ---- R8.6: the bounds, at the node --------------------------------------------------


def nested(depth: int) -> dict[str, Any]:
    tree: dict[str, Any] = {"city": {"$eq": "a"}}
    for _ in range(depth - 1):
        tree = {"$and": [tree]}
    return tree


async def test_r8_6_the_bounds_are_exact_and_point_at_the_node(api: Api) -> None:
    person = await api.person()
    for accepted in (
        nested(5),
        {"$or": [{"city": {"$eq": str(n)}} for n in range(50)]},
        {"city": {"$in": [str(n) for n in range(500)]}},
    ):
        answered = await api.query(person, {"filter": accepted})
        assert answered.status_code == 200, answered.text
    for refused, expected in (
        (nested(6), ("/filter" + "/$and/0" * 5, "filter_too_deep")),
        (
            {"$or": [{"city": {"$eq": str(n)}} for n in range(51)]},
            ("/filter/$or/50", "filter_too_many_leaves"),
        ),
        (
            {"city": {"$in": [str(n) for n in range(501)]}},
            ("/filter/city/$in", "filter_in_too_many_values"),
        ),
        ({"city": {"$eq": "é" * 512 + "x"}}, ("/filter/city/$eq", "filter_string_too_long")),
        ({"city": {"$ne": "a"}}, ("/filter", "operator_not_allowed")),
        ({"city": {"$eq": None}}, ("/filter/city/$eq", "operator_not_allowed")),
    ):
        assert errors(await api.query(person, {"filter": refused})) == [expected]
    # 1 024 bytes pass the bound; no field holds them (255 characters at most),
    # so the field's own length answers, as a write's would (gate (f)).
    at_bound = await api.query(person, {"filter": {"city": {"$eq": "é" * 512}}})
    assert errors(at_bound) == [("/filter/city/$eq", "invalid_type")]


# ---- R8.3, R8.7: three pages, and a cursor bound to its query ----------------------


async def test_r8_3_three_pages_by_name_return_each_match_once(api: Api) -> None:
    person = await api.person()
    made = set()
    for n in range(9):
        made.add(await api.make(person, ["Lan", "Lan", "Bảo"][n % 3], city="ba_trang"))
    body: dict[str, Any] = {"filter": {"city": {"$eq": "ba_trang"}}, "order_by": "name", "limit": 3}
    seen: list[str] = []
    names: list[str] = []
    for _ in range(3):
        page = (await api.query(person, body)).json()
        seen += [item["id"] for item in page["items"]]
        names += [item["name"] for item in page["items"]]
        body["cursor"] = page["next_cursor"]
    assert body["cursor"] is None
    assert sorted(seen) == sorted(made) and len(seen) == len(set(seen)) == 9
    assert names == ["Bảo"] * 3 + ["Lan"] * 6
    assert errors(await api.query(person, {"order_by": "city"})) == [
        ("order_by", "field_not_filterable")
    ]


async def test_r8_7_a_cursor_is_bound_to_its_filter_and_its_count(api: Api) -> None:
    person = await api.person()
    for n in range(3):
        await api.make(person, f"Con trỏ {n}", city="con_tro")
    first = await api.query(
        person, {"filter": {"city": {"$eq": "con_tro"}}, "limit": 1, "count": "exact"}
    )
    assert first.json()["count"] == 3 and first.json()["count_capped"] is False
    cursor = first.json()["next_cursor"]
    resumed = await api.query(
        person,
        {"filter": {"city": {"$eq": "con_tro"}}, "limit": 1, "count": "exact", "cursor": cursor},
    )
    assert resumed.status_code == 200 and "count" not in resumed.json()
    for body in (
        {"filter": {"city": {"$eq": "khac"}}, "limit": 1, "count": "exact", "cursor": cursor},
        {"filter": {"city": {"$eq": "con_tro"}}, "limit": 1, "cursor": cursor},
    ):
        assert errors(await api.query(person, body)) == [("cursor", "cursor_invalid")]
    # GET's cursor is POST's: one list, one route identity.
    listed = await api.call(person, "GET", base(), params={"limit": 1})
    again = await api.query(person, {"limit": 1, "cursor": listed.json()["next_cursor"]})
    assert again.status_code == 200, again.text


# ---- R3.3, R3.4, R4.3: the object, the key, the company ---------------------------


async def test_r3_3_another_companys_object_is_404_on_both_lists(api: Api) -> None:
    stranger = await api.person(tenant=api.b)
    for response in (
        await api.call(stranger, "GET", base(ONLY_A)),
        await api.call(stranger, "GET", base(ONLY_A), params={"count": "exact"}),
        await api.query(stranger, {"count": "exact"}, ONLY_A),
    ):
        assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_r3_4_co8_no_read_key_is_403_on_both_lists(api: Api) -> None:
    writer = await api.person({"create": "workspace"})
    for response in (
        await api.call(writer, "GET", base()),
        await api.query(writer, {"filter": {"khong_co": {"$eq": 1}}}),
    ):
        assert response.status_code == 403 and response.json()["code"] == "permission_denied"


async def test_r4_3_co1_each_company_lists_and_counts_its_own(api: Api) -> None:
    in_a, in_b = await api.person(), await api.person(tenant=api.b)
    await api.make(in_a, "Của A", city="hai_ben")
    of_b = await api.call(
        in_b, "POST", base(), json={"name": "Của B", "fields": {"city": "hai_ben"}}
    )
    page = (
        await api.query(in_b, {"filter": {"city": {"$eq": "hai_ben"}}, "count": "exact"})
    ).json()
    assert [item["id"] for item in page["items"]] == [of_b.json()["id"]]
    assert (page["count"], page["count_capped"]) == (1, False)


# ---- R3.6: one grammar ------------------------------------------------------------


async def test_r3_6_a_tree_the_projected_schema_admits_is_accepted(api: Api) -> None:
    reader = await api.person({"read": "workspace"}, {"name": "read", "city": "read"})
    sessions = sessions_of(api.container.engine)  # type: ignore[arg-type]
    assert api.container.studio is not None
    schemas = await api.container.studio.records.schemas(person_door(sessions, reader), LEAD)
    grammar = schemas.query["$defs"]
    assert "phone" not in grammar["node_1"]["properties"]
    tree = {
        "$and": [
            {"city": {"$in": ["a", "b"]}},
            {"$or": [{"name": {"$gte": "A"}}, {"created_at": {"$lt": "2030-01-01T00:00:00Z"}}]},
        ]
    }
    # Each member of the tree is one the grammar names, at its depth.
    assert {"$and", "city"} <= set(grammar["node_1"]["properties"])
    assert {"$in"} <= set(grammar["leaf_city"]["properties"])
    assert {"$or", "name", "created_at"} <= set(grammar["node_2"]["properties"])
    answered = await api.query(reader, {"filter": tree})
    assert answered.status_code == 200, answered.text


async def test_r8_2_describe_marks_only_name_sortable_among_the_fields(api: Api) -> None:
    # W1 sorts on `name`, `created_at` and `updated_at` (gate (b)); a slot filters only.
    person = await api.person()
    described = await api.call(person, "GET", f"/api/v1/studio/objects/{LEAD}/describe")
    flags = {f["api_name"]: (f["filterable"], f["sortable"]) for f in described.json()["fields"]}
    assert flags["name"] == (True, True)
    assert flags["city"] == (True, False)
    assert flags["note"] == (False, False)
