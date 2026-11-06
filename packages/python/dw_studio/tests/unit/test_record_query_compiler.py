"""`RecordQueryCompiler`'s statement text (custom-objects ticket 04; R8.9,
lượt xác nhận (m)).

RLS hides another company's rows whatever the statement says, so no
functional test goes red when the compiler forgets the company: only the
text can. Every statement it builds, a page in either direction on each of
the three orderings, with and without a filter and a cursor, and the count,
names `tenant_id = :tenant`, the object, and `deleted_at IS NULL`; a filter
is one parenthesised term beside them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa

from dw_kernel.filters import ListQuery, parse_query
from dw_kernel.pagination import CursorPosition, encode_cursor
from dw_studio.records.adapters.record_query import RecordQueryCompiler
from dw_studio.records.application.ports import AppliedObject, FieldStorage
from dw_studio.records.application.record_query import query_schema
from dw_studio.records.domain.document import definition_of

pytestmark = pytest.mark.unit

TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()


def lead() -> AppliedObject:
    definition = definition_of(
        {
            "labels": {"vi": "Khách"},
            "name_field": {"labels": {"vi": "Tên"}, "pd_category": "none"},
            "fields": [
                {
                    "api_name": "city",
                    "labels": {"vi": "Tỉnh"},
                    "type": "text",
                    "pd_category": "none",
                    "indexed": True,
                },
                {
                    "api_name": "note",
                    "labels": {"vi": "Ghi"},
                    "type": "text",
                    "pd_category": "none",
                },
            ],
        }
    )
    storage = {
        "name": FieldStorage(uuid.uuid4(), "system", None, None),
        "city": FieldStorage(uuid.uuid4(), "slot", "t01", None),
        "note": FieldStorage(uuid.uuid4(), "data", None, 1),
    }
    return AppliedObject(uuid.uuid4(), "lead", uuid.uuid4(), 1, definition, storage)


OBJ = lead()
SCHEMA = query_schema(OBJ, frozenset({"name", "city", "note"}))


def ask(**kw: Any) -> ListQuery:
    return parse_query(
        SCHEMA, route="/r", tenant=TENANT, workspace=WORKSPACE, limit=kw.pop("limit", 50), **kw
    )


def text(statement: sa.Select[Any]) -> str:
    return str(statement)


def statements() -> list[tuple[str, sa.Select[Any]]]:
    compiler = RecordQueryCompiler(TENANT)
    found: list[tuple[str, sa.Select[Any]]] = []
    for order in ("name", "name desc", "created_at", "created_at desc", "updated_at desc"):
        for tree in (None, {"$or": [{"city": {"$eq": "Huế"}}, {"name": {"$gt": "A"}}]}):
            first = ask(order_by=order, filter=tree)
            value: Any = "M" if order.startswith("name") else datetime(2026, 11, 6, tzinfo=UTC)
            cursor = encode_cursor(CursorPosition(value, uuid.uuid4()), first.page.query)
            for query in (first, ask(order_by=order, filter=tree, cursor=cursor)):
                page = compiler.page(OBJ, query)
                for phase in page.phases:
                    statement = page.statement.where(phase.where).order_by(*phase.order_by)
                    found.append((f"{order} {tree} {query.page.after}", statement))
        found.append((f"count {order}", compiler.count(OBJ, ask(order_by=order), 10_000)))
    return found


def test_r8_9_every_statement_names_the_bound_company() -> None:
    compiled = statements()
    assert len(compiled) > 20
    for label, statement in compiled:
        sql = text(statement)
        assert "studio.records.tenant_id = :tenant" in sql, label
        assert "studio.records.object_id = :object" in sql, label
        assert "studio.records.deleted_at IS NULL" in sql, label
        assert statement.compile().params["tenant"] == TENANT, label


def test_a_filter_is_one_term_and_its_values_are_bound() -> None:
    page = RecordQueryCompiler(TENANT).page(OBJ, ask(filter={"city": {"$in": ["Huế", "x'--"]}}))
    sql = text(page.statement)
    assert "((t01 IN (:qf_0, :qf_1)))" in sql and "x'--" not in sql


def test_name_orders_under_the_vietnamese_collation() -> None:
    page = RecordQueryCompiler(TENANT).page(OBJ, ask(order_by="name"))
    (phase,) = page.phases
    sql = text(page.statement.order_by(*phase.order_by))
    assert 'ORDER BY studio.records.name COLLATE "vi-VN-x-icu" ASC, studio.records.id ASC' in sql
