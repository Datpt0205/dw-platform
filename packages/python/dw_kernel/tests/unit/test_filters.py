"""`dw_kernel.filters` called directly, as a non-HTTP caller would (R5.13, APS40).

Every refusal here is the same one a route gives (the route only prefixes
`/filter`), so a tool, a workflow node or `RecordsPort` meets the same bounds,
the same closed schema and the same silence about what it sent.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from dw_kernel.filters import (
    MAX_IN_VALUES,
    ParsedFilter,
    QueryError,
    QueryField,
    QuerySchema,
    ReasonCode,
    compile_filter,
    loads,
    parse_fields,
    parse_filter,
    parse_order_by,
    parse_query,
)
from dw_kernel.pagination import CursorPosition, Phase, SortType, decode_cursor, encode_cursor

pytestmark = pytest.mark.unit

COMPARE = frozenset({"$eq", "$in", "$lt", "$lte", "$gt", "$gte"})
SCHEMA = QuerySchema(
    fields=(
        QueryField(
            "name", SortType.TEXT, "name", filterable=True, sortable=True, operators=COMPARE
        ),
        QueryField(
            "age", SortType.INT, "age_years", filterable=True, sortable=True, operators=COMPARE
        ),
        QueryField("flag", SortType.BOOL, "flag", filterable=True, operators=frozenset({"$eq"})),
        QueryField("born", SortType.DATE, "born", filterable=True, operators=COMPARE),
        QueryField("seen", SortType.DATETIME, "seen_at", filterable=True, operators=COMPARE),
        QueryField("score", SortType.FLOAT, "score", filterable=True, operators=COMPARE),
        # Declared and nothing else: closed by default.
        QueryField("note", SortType.TEXT, "note"),
    ),
    default_order=("name", False),
    logical=frozenset({"$and", "$or", "$not"}),
)
TENANT, WORKSPACE = uuid.uuid4(), uuid.uuid4()
SECRET = "SECRET-123"


def refused(tree: object, schema: QuerySchema = SCHEMA) -> tuple[ReasonCode, str | None]:
    with pytest.raises(QueryError) as raised:
        parse_filter(schema, tree)
    (problem,) = raised.value.problems
    return problem.code, problem.pointer


def nested(depth: int) -> dict[str, Any]:
    tree: dict[str, Any] = {"name": {"$eq": "a"}}
    for _ in range(depth - 1):
        tree = {"$and": [tree]}
    return tree


def query(**kw: Any) -> Any:
    return parse_query(
        SCHEMA, route="/things", tenant=TENANT, workspace=WORKSPACE, limit=kw.pop("limit", 10), **kw
    )


# ---------------------------------------------------------------- bounds --


def test_the_limits_are_accepted_exactly_and_refused_one_past() -> None:
    # R5.1, R5.8 (APS9): depth 5, 50 leaves, 500 values, 1 024 bytes.
    parse_filter(SCHEMA, nested(5))
    parse_filter(SCHEMA, {"$or": [{"age": {"$eq": n}} for n in range(50)]})
    parse_filter(SCHEMA, {"age": {"$in": list(range(MAX_IN_VALUES))}})
    parse_filter(SCHEMA, {"name": {"$eq": "é" * 512}})

    assert refused(nested(6)) == (ReasonCode.FILTER_TOO_DEEP, "/$and/0" * 5)
    assert refused({"$or": [{"age": {"$eq": n}} for n in range(51)]}) == (
        ReasonCode.FILTER_TOO_MANY_LEAVES,
        "/$or/50",
    )
    assert refused({"age": {"$in": list(range(501))}}) == (
        ReasonCode.FILTER_IN_TOO_MANY_VALUES,
        "/age/$in",
    )
    assert refused({"name": {"$eq": "é" * 512 + "x"}}) == (
        ReasonCode.FILTER_STRING_TOO_LONG,
        "/name/$eq",
    )


def test_depth_counts_nodes_from_the_root_to_a_leaf() -> None:
    parse_filter(SCHEMA, {"name": {"$eq": "a"}})
    parse_filter(SCHEMA, {"$not": {"$and": [{"name": {"$eq": "a"}}]}})
    assert refused({"$not": nested(5)})[0] is ReasonCode.FILTER_TOO_DEEP


# ------------------------------------------------------------- operators --


def test_an_operator_outside_a_types_table_is_not_allowed() -> None:
    # R5.2: `$gt` on a bool, pointed at the leaf.
    assert refused({"$and": [{"flag": {"$gt": True}}]}) == (
        ReasonCode.OPERATOR_NOT_ALLOWED,
        "/$and/0",
    )


@pytest.mark.parametrize("operator", ["$ne", "$like", "$regex"])
def test_operators_the_language_does_not_have_are_not_allowed(operator: str) -> None:
    assert refused({"name": {operator: "a"}}) == (ReasonCode.OPERATOR_NOT_ALLOWED, "")


def test_a_logical_operator_the_schema_does_not_take_is_not_allowed() -> None:
    # APS49: the logical set is closed when undeclared.
    closed = QuerySchema(fields=SCHEMA.fields, default_order=("name", False))
    assert refused({"$or": [{"name": {"$eq": "a"}}]}, closed) == (
        ReasonCode.OPERATOR_NOT_ALLOWED,
        "",
    )


@pytest.mark.parametrize(
    ("tree", "pointer"),
    [
        ({"name": {"$eq": "a"}, "age": {"$eq": 2}}, ""),
        ({"age": {"$gt": 1, "$lt": 5}}, ""),
        ({"$and": []}, "/$and"),
        ({"age": {"$eq": "seven"}}, "/age/$eq"),
        ({"age": {"$eq": True}}, "/age/$eq"),
        ({"age": {"$eq": 2**63}}, "/age/$eq"),
        ({"age": {"$in": [1, None]}}, "/age/$in/1"),
        ({"age": {"$in": []}}, "/age/$in"),
        ({"age": {"$lt": None}}, "/age/$lt"),
        ({"seen": {"$gt": "2026-10-28T09:00:00"}}, "/seen/$gt"),
        ({"born": {"$eq": "28/10/2026"}}, "/born/$eq"),
        ({"$not": [{"name": {"$eq": "a"}}]}, "/$not"),
        ([], ""),
    ],
)
def test_a_malformed_node_is_refused_where_it_stands(tree: object, pointer: str) -> None:
    # R5.8 and the leaf grammar of the spec's "API" section.
    assert refused(tree) == (ReasonCode.FILTER_MALFORMED, pointer)


@pytest.mark.parametrize("text", ['{"score": {"$eq": NaN}}', '{"score": {"$eq": Infinity}}'])
def test_nan_and_infinity_are_not_numbers(text: str) -> None:
    with pytest.raises(QueryError) as raised:
        parse_filter(SCHEMA, loads(text))
    assert raised.value.problems[0].code is ReasonCode.FILTER_MALFORMED


def test_a_key_named_twice_is_malformed_at_its_node() -> None:
    tree = loads('{"$and": [{"name": {"$eq": "a", "$eq": "b"}}]}')
    assert refused(tree) == (ReasonCode.FILTER_MALFORMED, "/$and/0")


def test_typed_values_are_read_as_their_type() -> None:
    parsed = parse_filter(
        SCHEMA,
        {
            "$and": [
                {"born": {"$eq": "2026-10-28"}},
                {"seen": {"$gte": "2026-10-28T09:00:00+07:00"}},
                {"score": {"$lt": 2}},
                {"name": {"$eq": None}},
            ]
        },
    )
    compiled = compile_filter(parsed)
    assert compiled.params == {
        "qf_0": date(2026, 10, 28),
        "qf_1": datetime.fromisoformat("2026-10-28T09:00:00+07:00"),
        "qf_2": 2.0,
    }
    assert "name IS NULL" in compiled.sql


# ---------------------------------------------------------------- fields --


def test_a_field_absent_from_the_schema_is_not_readable_and_not_named() -> None:
    # R5.6, R5.13: the same answer as a hidden field, at the leaf.
    assert refused({"$or": [{"name": {"$eq": "a"}}, {SECRET: {"$eq": 1}}]}) == (
        ReasonCode.FIELD_NOT_READABLE,
        "/$or/1",
    )


def test_a_field_that_does_not_declare_it_neither_filters_nor_sorts() -> None:
    # R5.15 (APS49): closed by default.
    assert refused({"note": {"$eq": "a"}}) == (ReasonCode.FIELD_NOT_FILTERABLE, "")
    with pytest.raises(QueryError) as raised:
        parse_order_by(SCHEMA, "note")
    assert raised.value.problems[0].code is ReasonCode.FIELD_NOT_FILTERABLE
    assert raised.value.problems[0].parameter == "order_by"
    with pytest.raises(QueryError):
        parse_order_by(SCHEMA, "flag desc")


def test_a_schema_cannot_declare_an_operator_its_type_lacks() -> None:
    with pytest.raises(ValueError):
        QueryField("flag", SortType.BOOL, "flag", filterable=True, operators=frozenset({"$gt"}))


# -------------------------------------------------------------- order_by --


def test_order_by_reads_one_field_and_a_direction() -> None:
    # R5.3.
    order = parse_order_by(SCHEMA, "name DESC")
    assert (order.field.name, order.descending) == ("name", True)
    assert parse_order_by(SCHEMA, "age").descending is False
    assert parse_order_by(SCHEMA, None).field.name == "name"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("name desc, age", ReasonCode.ORDER_BY_TOO_MANY_FIELDS),
        ("name desc, (select 1)", ReasonCode.ORDER_BY_TOO_MANY_FIELDS),
        ("name sideways", ReasonCode.ORDER_BY_MALFORMED),
        ("name  desc", ReasonCode.ORDER_BY_MALFORMED),
        ("(select 1)", ReasonCode.ORDER_BY_MALFORMED),
        ("", ReasonCode.ORDER_BY_MALFORMED),
        ("ghost", ReasonCode.FIELD_NOT_READABLE),
    ],
)
def test_order_by_is_refused_by_parameter(text: str, code: ReasonCode) -> None:
    # R5.4, R5.9, R5.11.
    with pytest.raises(QueryError) as raised:
        parse_order_by(SCHEMA, text)
    (problem,) = raised.value.problems
    assert (problem.code, problem.parameter, problem.pointer) == (code, "order_by", None)


def test_fields_names_schema_fields_and_always_may_name_id() -> None:
    # R5.5.
    assert parse_fields(SCHEMA, "name") == ("name",)
    assert parse_fields(SCHEMA, "id,name,name") == ("id", "name")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("name,,id", ReasonCode.FIELDS_MALFORMED),
        ("id,pg_sleep(1)", ReasonCode.FIELDS_MALFORMED),
        ("name, id", ReasonCode.FIELDS_MALFORMED),
        ("ghost", ReasonCode.FIELD_NOT_READABLE),
    ],
)
def test_fields_is_refused_by_parameter(text: str, code: ReasonCode) -> None:
    with pytest.raises(QueryError) as raised:
        parse_fields(SCHEMA, text)
    assert raised.value.problems[0].code is code
    assert raised.value.problems[0].parameter == "fields"


# ---------------------------------------------------- what an error says --


@pytest.mark.parametrize(
    "tree",
    [
        {"name": {"$eq": SECRET + "x" * 1024}},
        {"age": {"$eq": SECRET}},
        {SECRET: {"$eq": 1}},
        {"$and": [{"name": {"$eq": "a"}}], SECRET: 1},
        {"name": {SECRET: 1}},
    ],
    ids=["too-long", "wrong-type", "unknown-field", "unknown-key", "unknown-operator"],
)
def test_a_refusal_carries_no_value_or_key_the_caller_sent(tree: object) -> None:
    # R5.14 (APS48): not in the detail, the pointer, or the exception's text.
    with pytest.raises(QueryError) as raised:
        parse_filter(SCHEMA, tree)
    error = raised.value
    rendered = [str(error), repr(error.args), error.message, json.dumps(error.details)]
    rendered += [f"{p.code} {p.pointer} {p.parameter} {p.detail}" for p in error.problems]
    assert not any(SECRET in text for text in rendered)


# ------------------------------------------------------------- compiling --


def test_values_are_bound_and_columns_come_from_the_schema() -> None:
    # R5.10 (APS25): the value is a parameter, the name the schema's column.
    injection = "x'); DROP TABLE t; --"
    compiled = compile_filter(
        parse_filter(SCHEMA, {"$and": [{"name": {"$eq": injection}}, {"age": {"$in": [1, 2]}}]})
    )
    assert compiled.sql == "(((name = :qf_0) AND (age_years IN (:qf_1, :qf_2))))"
    assert injection not in compiled.sql
    assert compiled.params == {"qf_0": injection, "qf_1": 1, "qf_2": 2}


def test_the_compiled_tree_is_one_parenthesised_term() -> None:
    # APS45: `scope AND (a OR b)`, never `scope AND a OR b`, which would let
    # the second arm read past the scope.
    compiled = compile_filter(
        parse_filter(SCHEMA, {"$or": [{"name": {"$eq": "b"}}, {"name": {"$eq": "a"}}]})
    )
    assert compiled.sql == "(((name = :qf_0) OR (name = :qf_1)))"


def test_not_matches_rows_whose_inner_condition_is_null() -> None:
    compiled = compile_filter(parse_filter(SCHEMA, {"$not": {"age": {"$gt": 3}}}))
    assert compiled.sql == "((NOT COALESCE((age_years > :qf_0), false)))"


def test_the_compiler_takes_only_a_parsed_tree() -> None:
    # APS40: a tree that skipped the parser skipped every bound and check.
    with pytest.raises(TypeError):
        compile_filter({"name": {"$eq": "a"}})  # type: ignore[arg-type]
    leaf = parse_filter(SCHEMA, {"name": {"$eq": "a"}}).root
    with pytest.raises(TypeError):
        compile_filter(leaf)  # type: ignore[arg-type]
    assert isinstance(parse_filter(SCHEMA, {"name": {"$eq": "a"}}), ParsedFilter)


# ------------------------------------------------------------- the query --


def test_a_whole_query_is_refused_before_anything_runs() -> None:
    # APS40: the same reasons as through a route.
    for kw, code in (
        ({"filter": nested(6)}, ReasonCode.FILTER_TOO_DEEP),
        ({"filter": {SECRET: {"$eq": 1}}}, ReasonCode.FIELD_NOT_READABLE),
        ({"order_by": "name sideways"}, ReasonCode.ORDER_BY_MALFORMED),
        ({"cursor": "not-a-cursor"}, ReasonCode.CURSOR_INVALID),
        ({"limit": 201}, ReasonCode.LIMIT_OUT_OF_RANGE),
        ({"limit": 0}, ReasonCode.LIMIT_OUT_OF_RANGE),
    ):
        with pytest.raises(QueryError) as raised:
            query(**kw)
        assert raised.value.problems[0].code is code, kw


def test_a_cursor_is_bound_to_the_filter_ordering_and_fields_it_was_issued_for() -> None:
    # R4.3, R4.5.
    first = query(filter={"name": {"$gt": "a"}}, order_by="age desc", fields="name")
    cursor = encode_cursor(CursorPosition(sort_value=30, tiebreaker=uuid.uuid4()), first.page.query)

    again = query(filter={"name": {"$gt": "a"}}, order_by="age DESC", fields="name", cursor=cursor)
    assert again.page.after is not None and again.page.after.sort_value == 30

    for kw in (
        {"filter": {"name": {"$gt": "b"}}, "order_by": "age desc", "fields": "name"},
        {"filter": {"name": {"$gt": "a"}}, "order_by": "age", "fields": "name"},
        {"filter": {"name": {"$gt": "a"}}, "order_by": "age desc", "fields": "age"},
        {"filter": {"name": {"$gt": "a"}}, "order_by": "age desc"},
    ):
        with pytest.raises(QueryError) as raised:
            query(cursor=cursor, **kw)
        assert raised.value.problems[0].code is ReasonCode.CURSOR_INVALID


def test_the_same_tree_in_another_key_order_takes_the_same_cursor() -> None:
    # R4.5.
    one = query(filter={"$and": [{"name": {"$eq": "a"}}, {"age": {"$in": [1, 2]}}]})
    cursor = encode_cursor(CursorPosition(sort_value="m", tiebreaker=uuid.uuid4()), one.page.query)
    reordered = loads('{"$and": [{"name": {"$eq": "a"}}, {"age": {"$in": [1, 2]}}]}')
    assert query(filter=reordered, cursor=cursor).page.after is not None


def test_a_cursor_is_bound_to_the_route_and_the_callers_workspace() -> None:
    one = query()
    cursor = encode_cursor(CursorPosition(sort_value="m", tiebreaker=uuid.uuid4()), one.page.query)
    for route, workspace in (("/other", WORKSPACE), ("/things", uuid.uuid4())):
        with pytest.raises(QueryError):
            parse_query(
                SCHEMA, route=route, tenant=TENANT, workspace=workspace, cursor=cursor, limit=10
            )


def test_a_nulls_cursor_resumes_among_the_nulls() -> None:
    one = query(order_by="age")
    position = CursorPosition(sort_value=None, tiebreaker=uuid.uuid4())
    cursor = encode_cursor(position, one.page.query)
    after = query(order_by="age", cursor=cursor).page.after
    assert after == position and after.phase is Phase.NULLS
    assert decode_cursor(cursor, one.page.query).phase is Phase.NULLS


def test_a_datetime_cursor_keeps_its_offset() -> None:
    seen = datetime(2026, 10, 28, 9, tzinfo=UTC)
    schema = QuerySchema(
        fields=(QueryField("seen", SortType.DATETIME, "seen_at", sortable=True),),
        default_order=("seen", True),
    )
    one = parse_query(schema, route="/x", tenant=TENANT, workspace=None, limit=5)
    cursor = encode_cursor(CursorPosition(sort_value=seen, tiebreaker=uuid.uuid4()), one.page.query)
    again = parse_query(schema, route="/x", tenant=TENANT, workspace=None, limit=5, cursor=cursor)
    assert again.page.after is not None and again.page.after.sort_value == seen


def test_a_cursor_is_bound_to_the_callers_tenant_with_no_workspace() -> None:
    # R4.4: a listing read tenant-wide (no workspace) still refuses another
    # tenant's cursor.
    one = parse_query(SCHEMA, route="/things", tenant=TENANT, workspace=None, limit=5)
    cursor = encode_cursor(CursorPosition(sort_value="m", tiebreaker=uuid.uuid4()), one.page.query)
    with pytest.raises(QueryError) as raised:
        parse_query(
            SCHEMA, route="/things", tenant=uuid.uuid4(), workspace=None, cursor=cursor, limit=5
        )
    assert raised.value.problems[0].code is ReasonCode.CURSOR_INVALID
