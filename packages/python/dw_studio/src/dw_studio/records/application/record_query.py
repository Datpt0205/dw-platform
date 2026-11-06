"""What one caller may ask of an object's record list, as a `QuerySchema`
(custom-objects ticket 04; R8; ADR-0108 decision 2).

The one builder of that schema, read by both its consumers: `RecordService`,
which parses a list query against it before any record SQL runs, and the
schema projector, which exports its JSON Schema so a tool, a workflow step
and the route share one grammar (gate (h)). The language itself (bounds,
operators, pointers, the cursor) is `dw_kernel.filters`'s; this module only
says which fields a caller has and what each compiles to.

- A field the caller cannot read is absent: naming it in a filter, in
  `order_by` or in `fields` is `field_not_readable` (R8.4), the same answer as
  a field that does not exist. A readable field in `data` is present and does
  not filter: `field_not_filterable` (R8.5).
- A slot filters with `$eq`, `$in`, `$lt`, `$lte`, `$gt`, `$gte`, a boolean
  slot with `$eq` only; `name`, `created_at` and `updated_at` the same as a
  slot; `owner` and `workspace` with `$eq` and `$in` (their indexes carry
  them). No field takes a `null` operand: a slot's partial index holds only
  values (gate (b)).
- W1 sorts on `name`, `created_at` and `updated_at`, three NOT NULL columns
  each with an index `(tenant_id, object_id, <column>, id)`; a slot does not
  sort until its NULLs have an index (R8.2, R8.3; gate (b), (c)).
- Every value of a leaf goes through the write's coercion first
  (`filter_value`), so a phone is compared in E.164 and a decimal string as
  its scaled integer (gate (f)).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from functools import partial
from typing import Final

from dw_kernel.filters import COMPARISONS, QueryField, QuerySchema
from dw_kernel.pagination import SortType
from dw_studio.records.application.ports import AppliedObject
from dw_studio.records.domain.document import NAME, OWNER, WORKSPACE, FieldDefinition
from dw_studio.records.domain.values import filter_value

CREATED_AT: Final = "created_at"
UPDATED_AT: Final = "updated_at"
# What W1 sorts on: NOT NULL, each carried by `(tenant_id, object_id, <col>, id)`.
SORTABLE: Final = (NAME, CREATED_AT, UPDATED_AT)
# `GET <list>` takes these only: a `name` cursor carries a value and stays in a
# `POST .../query` body, never in a URL (gate (g), ADR-0106 decision 4).
URL_SORTABLE: Final = frozenset({CREATED_AT, UPDATED_AT})
DEFAULT_ORDER: Final = (CREATED_AT, True)
# `count=exact` counts this many matches at most (R8.8).
COUNT_CAP: Final = 10_000

_BY_FAMILY: Final[Mapping[str, SortType]] = {
    "t": SortType.TEXT,
    "u": SortType.TEXT,
    "i": SortType.INT,
    "f": SortType.FLOAT,
    "d": SortType.DATE,
    "z": SortType.DATETIME,
    "b": SortType.BOOL,
}
_EQ_IN: Final = frozenset({"$eq", "$in"})
# The column of a readable field that does not filter or sort. Never
# compiled: the kernel compiles only a filterable leaf and a sortable order.
_UNCOMPILED: Final = "data"


def _uuid_text(raw: object) -> object:
    if not isinstance(raw, str):
        raise ValueError("not an id")
    return str(uuid.UUID(raw))


def _coerced(definition: FieldDefinition) -> partial[object]:
    return partial(filter_value, definition)


def _slot_field(definition: FieldDefinition, slot: str) -> QueryField:
    type_ = _BY_FAMILY[slot[0]]
    return QueryField(
        definition.api_name,
        type_,
        slot,
        filterable=True,
        operators=frozenset({"$eq"}) if type_ is SortType.BOOL else COMPARISONS,
        null_allowed=False,
        coerce=_coerced(definition),
    )


def query_schema(obj: AppliedObject, readable: frozenset[str]) -> QuerySchema:
    """The list query a caller may send on ``obj``, ``readable`` the fields
    its field decision does not hide (`readable_names`)."""
    fields: list[QueryField] = []
    definitions = obj.definition.fields
    if NAME in readable:
        fields.append(
            QueryField(
                NAME,
                SortType.TEXT,
                NAME,
                filterable=True,
                sortable=True,
                operators=COMPARISONS,
                null_allowed=False,
                coerce=_coerced(definitions[NAME]),
            )
        )
    for stamp in (CREATED_AT, UPDATED_AT):
        fields.append(
            QueryField(
                stamp,
                SortType.DATETIME,
                stamp,
                filterable=True,
                sortable=True,
                operators=COMPARISONS,
                null_allowed=False,
            )
        )
    # System columns every reader of the record sees (ADR-0105).
    for name, column in ((OWNER, "owner_id"), (WORKSPACE, "workspace_id")):
        fields.append(
            QueryField(
                name,
                SortType.TEXT,
                column,
                filterable=True,
                operators=_EQ_IN,
                null_allowed=False,
                coerce=_uuid_text,
            )
        )
    for api_name in sorted(definitions):
        if api_name == NAME or api_name not in readable:
            continue
        storage = obj.storage[api_name]
        if storage.storage_kind == "slot" and storage.slot is not None:
            fields.append(_slot_field(definitions[api_name], storage.slot))
        else:
            fields.append(QueryField(api_name, SortType.TEXT, _UNCOMPILED))
    return QuerySchema(
        fields=tuple(fields), default_order=DEFAULT_ORDER, logical=frozenset({"$and", "$or"})
    )
