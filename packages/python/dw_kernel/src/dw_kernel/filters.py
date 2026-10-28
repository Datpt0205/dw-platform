"""The one door a list query comes through: filter tree, ordering, fields, cursor.

app-standards R5 (ADR-0108 point 2). A list that lets a caller pick rows hands
them a small language, and every property that language needs holds here, for
every caller — a route, `RecordsPort`, an agent's tool, a workflow node
(R5.13) — because none of them parses or compiles a query on its own:

* **Bounded.** Depth 5, 50 leaves, 500 values in an `$in`, 1 024 UTF-8 bytes in
  a string (R5.1), counted as the spec's "API" section counts them.
* **Typed and closed.** Each field of a :class:`QuerySchema` names its type,
  whether it filters and sorts, the operators its index carries and the column
  it compiles to. What the schema does not declare is refused: an operator not
  listed, a logical operator not listed, a field not filterable
  (`field_not_filterable`), a field absent from the schema
  (`field_not_readable`, the same answer as a hidden field, custom-objects:R8.4).
  The schema is built by the resource's owner, for the caller; this module does
  not know who may read what.
* **Values never reach SQL.** :func:`compile_filter` takes only a tree
  :func:`parse_filter` produced, takes every column name from the schema and
  every value as a bind parameter, and returns one parenthesised predicate the
  caller ANDs beside its own scope (R5.10) — never in place of it.
* **Errors say where, never what.** A :class:`QueryError` carries reason codes,
  a JSON pointer from the tree's root or a parameter name, and a fixed sentence
  per code: never a value or a key the caller sent (R5.14). A key absent from
  the schema is located at the node holding it.

Standard library only: the kernel has no SQL dependency, and the compiled form
is text with named parameters (`:qf_0`) that any SQL layer binds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from dw_kernel.errors import DomainError
from dw_kernel.pagination import (
    MAX_PAGE_SIZE,
    InvalidCursorError,
    PageQuery,
    PageRequest,
    SortType,
    SortValue,
    canonical_json,
    decode_cursor,
    list_identity,
    typed_value,
)

MAX_DEPTH: Final = 5
MAX_LEAVES: Final = 50
MAX_IN_VALUES: Final = 500
MAX_STRING_BYTES: Final = 1024

FieldType = SortType
"""The abstract type of a field: the cursor's tags and the operator table's rows."""

COMPARISONS: Final = frozenset({"$eq", "$in", "$lt", "$lte", "$gt", "$gte"})
LOGICAL: Final = frozenset({"$and", "$or", "$not"})
OPERATORS_BY_TYPE: Final[Mapping[FieldType, frozenset[str]]] = {
    FieldType.TEXT: COMPARISONS,
    FieldType.INT: COMPARISONS,
    FieldType.FLOAT: COMPARISONS,
    FieldType.DATE: COMPARISONS,
    FieldType.DATETIME: COMPARISONS,
    FieldType.BOOL: frozenset({"$eq"}),
}
_SQL_COMPARISON: Final = {"$eq": "=", "$lt": "<", "$lte": "<=", "$gt": ">", "$gte": ">="}

_NAME: Final = r"[A-Za-z_][A-Za-z0-9_]*"
_ORDER_ITEM: Final = re.compile(rf"(?P<name>{_NAME})(?: (?P<direction>asc|desc))?", re.IGNORECASE)
_FIELDS: Final = re.compile(rf"{_NAME}(?:,{_NAME})*")
_NAME_ONLY: Final = re.compile(_NAME)

# A field every listing returns and orders by last; `fields` may always name it.
ID_FIELD: Final = "id"


class ReasonCode(StrEnum):
    """`errors[].code` of a refused list query; `code` above it is always
    `validation_failed` (the spec's "API" section)."""

    FILTER_TOO_DEEP = "filter_too_deep"
    FILTER_TOO_MANY_LEAVES = "filter_too_many_leaves"
    FILTER_IN_TOO_MANY_VALUES = "filter_in_too_many_values"
    FILTER_STRING_TOO_LONG = "filter_string_too_long"
    OPERATOR_NOT_ALLOWED = "operator_not_allowed"
    FILTER_MALFORMED = "filter_malformed"
    FIELD_NOT_READABLE = "field_not_readable"
    FIELD_NOT_FILTERABLE = "field_not_filterable"
    ORDER_BY_TOO_MANY_FIELDS = "order_by_too_many_fields"
    ORDER_BY_MALFORMED = "order_by_malformed"
    FIELDS_MALFORMED = "fields_malformed"
    CURSOR_INVALID = "cursor_invalid"
    LIMIT_OUT_OF_RANGE = "limit_out_of_range"
    PARAMETER_REPEATED = "parameter_repeated"
    PARAMETER_NOT_ACCEPTED = "parameter_not_accepted"


# One sentence per code, written here and nowhere else: `detail` never carries
# what the caller sent (R5.14).
_DETAIL: Final[Mapping[ReasonCode, str]] = {
    ReasonCode.FILTER_TOO_DEEP: f"the filter is nested deeper than {MAX_DEPTH} levels",
    ReasonCode.FILTER_TOO_MANY_LEAVES: f"the filter has more than {MAX_LEAVES} conditions",
    ReasonCode.FILTER_IN_TOO_MANY_VALUES: f"an $in lists more than {MAX_IN_VALUES} values",
    ReasonCode.FILTER_STRING_TOO_LONG: f"a value is longer than {MAX_STRING_BYTES} bytes",
    ReasonCode.OPERATOR_NOT_ALLOWED: "this operator is not available here",
    ReasonCode.FILTER_MALFORMED: "this part of the filter is not well formed",
    ReasonCode.FIELD_NOT_READABLE: "this field is not available",
    ReasonCode.FIELD_NOT_FILTERABLE: "this field cannot be used to filter or sort",
    ReasonCode.ORDER_BY_TOO_MANY_FIELDS: "order_by takes one field",
    ReasonCode.ORDER_BY_MALFORMED: "order_by is a field name, optionally followed by asc or desc",
    ReasonCode.FIELDS_MALFORMED: "fields is a comma-separated list of field names",
    ReasonCode.CURSOR_INVALID: "the cursor is not readable here; request the first page again",
    ReasonCode.LIMIT_OUT_OF_RANGE: f"limit must be between 1 and {MAX_PAGE_SIZE}",
    ReasonCode.PARAMETER_REPEATED: "this parameter may be sent once",
    ReasonCode.PARAMETER_NOT_ACCEPTED: "this listing does not take this parameter",
}


@dataclass(frozen=True, slots=True)
class QueryProblem:
    """One thing wrong with a list query: a reason, and exactly one of a JSON
    pointer from the filter tree's root or the name of the parameter."""

    code: ReasonCode
    pointer: str | None = None
    parameter: str | None = None

    @property
    def detail(self) -> str:
        return _DETAIL[self.code]


class QueryError(DomainError):
    """A list query refused before any SQL ran: `validation_failed`, with the
    problems. A route prefixes each pointer with `/filter` and answers 422; a
    caller outside HTTP gets this exception itself (R5.13)."""

    def __init__(self, *problems: QueryProblem) -> None:
        super().__init__("the list query is not valid")
        self.problems = problems


def _problem(
    code: ReasonCode, *, pointer: str | None = None, parameter: str | None = None
) -> QueryError:
    return QueryError(QueryProblem(code, pointer=pointer, parameter=parameter))


@dataclass(frozen=True, slots=True)
class QueryField:
    """One field a listing exposes, as its owner built it for this caller.

    Closed by default: a field that does not say it filters or sorts does
    neither, and one that lists no operators takes none (R5.15)."""

    name: str
    type: FieldType
    column: str
    filterable: bool = False
    sortable: bool = False
    operators: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not _NAME_ONLY.fullmatch(self.name) or not _NAME_ONLY.fullmatch(self.column):
            raise ValueError("a field and its column are plain identifiers")
        if not self.operators <= OPERATORS_BY_TYPE[self.type]:
            raise ValueError("an operator outside the field type's table")


@dataclass(frozen=True, slots=True)
class OrderBy:
    field: QueryField
    descending: bool


@dataclass(frozen=True)
class QuerySchema:
    """What one caller may ask of one listing (the spec's "API" section).

    ``logical`` is the set of `$and`, `$or`, `$not` the listing takes, empty
    unless declared; ``default_order`` is the ordering when `order_by` is
    absent, ``(field name, descending)``."""

    fields: tuple[QueryField, ...]
    default_order: tuple[str, bool]
    logical: frozenset[str] = frozenset()
    _by_name: Mapping[str, QueryField] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name = {f.name: f for f in self.fields}
        if len(by_name) != len(self.fields) or not self.logical <= LOGICAL:
            raise ValueError("duplicate fields, or an unknown logical operator")
        if self.default_order[0] not in by_name:
            raise ValueError("the default order names no field of the schema")
        object.__setattr__(self, "_by_name", by_name)

    def get(self, name: str) -> QueryField | None:
        return self._by_name.get(name)

    @property
    def default(self) -> OrderBy:
        name, descending = self.default_order
        return OrderBy(field=self._by_name[name], descending=descending)


# ------------------------------------------------------------- the tree --


@dataclass(frozen=True, slots=True)
class Leaf:
    field: QueryField
    operator: str
    value: SortValue | tuple[SortValue, ...]


@dataclass(frozen=True, slots=True)
class Logical:
    operator: str
    nodes: tuple[Leaf | Logical, ...]


@dataclass(frozen=True, slots=True)
class ParsedFilter:
    """A tree :func:`parse_filter` accepted: the only input
    :func:`compile_filter` takes. ``canonical`` is the tree as it came, in
    sorted-key JSON, for the cursor's fingerprint."""

    root: Leaf | Logical
    canonical: object


class _DuplicateKeys(dict[str, object]):
    """An object whose JSON text named one key twice: malformed where it stands."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen = dict(pairs)
    return _DuplicateKeys(seen) if len(seen) != len(pairs) else seen


def _no_constant(_: str) -> object:
    raise ValueError("NaN and Infinity are not JSON")


def loads(text: str | bytes) -> object:
    """JSON as a list query reads it, for the `filter` parameter and a
    `POST <list>/query` body alike (R5.7): a key named twice is kept visible so
    the node is refused, and `NaN`/`Infinity` are not numbers."""
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except ValueError:
        raise _problem(ReasonCode.FILTER_MALFORMED, pointer="") from None


def _step(pointer: str, token: str) -> str:
    return pointer + "/" + token.replace("~", "~0").replace("/", "~1")


@dataclass
class _Walk:
    schema: QuerySchema
    leaves: int = 0


def _single(raw: object) -> tuple[str, object] | None:
    if isinstance(raw, dict) and not isinstance(raw, _DuplicateKeys) and len(raw) == 1:
        ((key, value),) = raw.items()
        return key, value
    return None


def _value(field_: QueryField, raw: object, pointer: str) -> SortValue:
    if isinstance(raw, str) and len(raw.encode("utf-8")) > MAX_STRING_BYTES:
        raise _problem(ReasonCode.FILTER_STRING_TOO_LONG, pointer=pointer)
    try:
        return typed_value(field_.type, raw)
    except ValueError:
        raise _problem(ReasonCode.FILTER_MALFORMED, pointer=pointer) from None


def _leaf(walk: _Walk, name: str, condition: object, pointer: str) -> Leaf:
    walk.leaves += 1
    if walk.leaves > MAX_LEAVES:
        raise _problem(ReasonCode.FILTER_TOO_MANY_LEAVES, pointer=pointer)
    field_ = walk.schema.get(name)
    if field_ is None:
        # Located at the leaf, not at the key: the name is the caller's.
        raise _problem(ReasonCode.FIELD_NOT_READABLE, pointer=pointer)
    if not field_.filterable:
        raise _problem(ReasonCode.FIELD_NOT_FILTERABLE, pointer=pointer)
    single = _single(condition)
    if single is None:
        raise _problem(ReasonCode.FILTER_MALFORMED, pointer=pointer)
    operator, operand = single
    if operator not in COMPARISONS:
        code = (
            ReasonCode.OPERATOR_NOT_ALLOWED
            if operator.startswith("$")
            else ReasonCode.FILTER_MALFORMED
        )
        raise _problem(code, pointer=pointer)
    if operator not in field_.operators:
        raise _problem(ReasonCode.OPERATOR_NOT_ALLOWED, pointer=pointer)
    at = _step(_step(pointer, field_.name), operator)
    if operator == "$in":
        if not isinstance(operand, list) or not operand:
            raise _problem(ReasonCode.FILTER_MALFORMED, pointer=at)
        if len(operand) > MAX_IN_VALUES:
            raise _problem(ReasonCode.FILTER_IN_TOO_MANY_VALUES, pointer=at)
        values = []
        for index, item in enumerate(operand):
            if item is None:
                raise _problem(ReasonCode.FILTER_MALFORMED, pointer=_step(at, str(index)))
            values.append(_value(field_, item, _step(at, str(index))))
        return Leaf(field_, operator, tuple(values))
    if operand is None:
        if operator != "$eq":
            raise _problem(ReasonCode.FILTER_MALFORMED, pointer=at)
        return Leaf(field_, operator, None)
    return Leaf(field_, operator, _value(field_, operand, at))


def _node(walk: _Walk, raw: object, pointer: str, depth: int) -> Leaf | Logical:
    if depth > MAX_DEPTH:
        raise _problem(ReasonCode.FILTER_TOO_DEEP, pointer=pointer)
    single = _single(raw)
    if single is None:
        raise _problem(ReasonCode.FILTER_MALFORMED, pointer=pointer)
    key, value = single
    if not key.startswith("$"):
        return _leaf(walk, key, value, pointer)
    if key not in LOGICAL or key not in walk.schema.logical:
        raise _problem(ReasonCode.OPERATOR_NOT_ALLOWED, pointer=pointer)
    at = _step(pointer, key)
    if key == "$not":
        # Exactly one node, not a list of them.
        return Logical(key, (_node(walk, value, at, depth + 1),))
    if not isinstance(value, list) or not value:
        raise _problem(ReasonCode.FILTER_MALFORMED, pointer=at)
    return Logical(
        key,
        tuple(_node(walk, item, _step(at, str(i)), depth + 1) for i, item in enumerate(value)),
    )


def parse_filter(schema: QuerySchema, tree: object) -> ParsedFilter:
    """Check a filter tree against ``schema``; :class:`QueryError` otherwise.

    Pointers are from the tree's root (`""` is the root node itself)."""
    root = _node(_Walk(schema), tree, "", 1)
    return ParsedFilter(root=root, canonical=json.loads(canonical_json(tree)))


def parse_order_by(schema: QuerySchema, text: str | None) -> OrderBy:
    """AIP-132 with one field (R5.3, R5.9, R5.11); the schema's default without one."""
    if text is None:
        return schema.default
    items = [item.strip() for item in text.split(",")]
    if len(items) > 1:
        raise _problem(ReasonCode.ORDER_BY_TOO_MANY_FIELDS, parameter="order_by")
    match = _ORDER_ITEM.fullmatch(items[0])
    if match is None:
        raise _problem(ReasonCode.ORDER_BY_MALFORMED, parameter="order_by")
    field_ = schema.get(match["name"])
    if field_ is None:
        raise _problem(ReasonCode.FIELD_NOT_READABLE, parameter="order_by")
    if not field_.sortable:
        raise _problem(ReasonCode.FIELD_NOT_FILTERABLE, parameter="order_by")
    direction = (match["direction"] or "asc").lower()
    return OrderBy(field=field_, descending=direction == "desc")


def parse_fields(schema: QuerySchema, text: str | None) -> tuple[str, ...] | None:
    """The fields to return besides `id` (R5.5), or None for all of them."""
    if text is None:
        return None
    if not _FIELDS.fullmatch(text):
        raise _problem(ReasonCode.FIELDS_MALFORMED, parameter="fields")
    names = tuple(dict.fromkeys(text.split(",")))
    if any(name != ID_FIELD and schema.get(name) is None for name in names):
        raise _problem(ReasonCode.FIELD_NOT_READABLE, parameter="fields")
    return names


@dataclass(frozen=True, slots=True)
class ListQuery:
    """A list query every part of which was checked, and the page it asks for."""

    filter: ParsedFilter | None
    order: OrderBy
    fields: tuple[str, ...] | None
    page: PageRequest


def parse_query(
    schema: QuerySchema,
    *,
    route: str,
    tenant: object,
    workspace: object | None,
    filter: object | None = None,
    order_by: str | None = None,
    fields: str | None = None,
    cursor: str | None = None,
    limit: int,
    params: Mapping[str, object] | None = None,
) -> ListQuery:
    """Every part of a list query, checked before any SQL runs.

    The cursor is bound to all of it (R4.3): the route, ``params``, the tenant
    and workspace of the caller's verified context, the filter, the ordering
    and the fields; one issued for any other query, or unreadable, is refused
    here like every other part (R4.6, R5.13)."""
    parsed = None if filter is None else parse_filter(schema, filter)
    order = parse_order_by(schema, order_by)
    chosen = parse_fields(schema, fields)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise _problem(ReasonCode.LIMIT_OUT_OF_RANGE, parameter="limit")
    query = PageQuery(
        key=None,
        identity=list_identity(
            route=route,
            tenant=tenant,
            workspace=workspace,
            params=params,
            selection={
                "filter": None if parsed is None else parsed.canonical,
                "order_by": [order.field.name, "desc" if order.descending else "asc"],
                "fields": None if chosen is None else list(chosen),
            },
        ),
        sort_type=order.field.type,
    )
    try:
        after = None if cursor is None else decode_cursor(cursor, query)
    except InvalidCursorError:
        raise _problem(ReasonCode.CURSOR_INVALID, parameter="cursor") from None
    return ListQuery(
        filter=parsed,
        order=order,
        fields=chosen,
        page=PageRequest(limit=limit, after=after, query=query),
    )


# ------------------------------------------------------------- compiling --


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    """One parenthesised predicate and its bind parameters.

    The caller ANDs it beside its own scope (`object_id`, `run_id`, owner),
    which it never replaces (R5.10)."""

    sql: str
    params: Mapping[str, SortValue]


@dataclass
class _Binds:
    prefix: str
    values: dict[str, SortValue] = field(default_factory=dict)

    def bind(self, value: SortValue) -> str:
        name = f"{self.prefix}_{len(self.values)}"
        self.values[name] = value
        return f":{name}"


def _compile(node: Leaf | Logical, binds: _Binds) -> str:
    if isinstance(node, Logical):
        parts = [_compile(child, binds) for child in node.nodes]
        if node.operator == "$not":
            # A NULL inside is "not true": `$not` matches it (the spec's "API").
            return f"(NOT COALESCE({parts[0]}, false))"
        joiner = " AND " if node.operator == "$and" else " OR "
        return "(" + joiner.join(parts) + ")"
    column = node.field.column
    if node.operator == "$in":
        assert isinstance(node.value, tuple)
        return f"({column} IN (" + ", ".join(binds.bind(v) for v in node.value) + "))"
    if node.value is None:
        return f"({column} IS NULL)"
    assert not isinstance(node.value, tuple)
    return f"({column} {_SQL_COMPARISON[node.operator]} {binds.bind(node.value)})"


def compile_filter(parsed: ParsedFilter, *, prefix: str = "qf") -> CompiledFilter:
    """SQL for a parsed tree: columns from the schema, values as parameters."""
    if not isinstance(parsed, ParsedFilter):
        # A tree that did not come through `parse_filter` skipped every bound
        # and every check of the schema.
        raise TypeError("compile_filter takes a tree parse_filter accepted")
    if not _NAME_ONLY.fullmatch(prefix):
        raise ValueError("a bind prefix is a plain identifier")
    binds = _Binds(prefix)
    return CompiledFilter(sql="(" + _compile(parsed.root, binds) + ")", params=binds.values)
