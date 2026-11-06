"""`RecordQueryCompiler`: the SQL of a record list (custom-objects ticket 04;
R8.1, R8.8, R8.9; ADR-0108 decision 2).

Not a second compiler. A list query reaches here parsed by `dw_kernel.filters`
against the caller's `QuerySchema` (`record_query`): its bounds, operators
and columns were checked there, its filter compiles there (`compile_filter`,
values as bind parameters), and the keyset clauses are `keyset`'s. This module
only puts them around the one scope every statement of the list carries,
written once:

    tenant_id = :tenant AND object_id = :object AND deleted_at IS NULL

`:tenant` is the bound company, never the request (R8.9): RLS would hide
another company's rows anyway, which is exactly why a functional test cannot
see the predicate go missing, and the hash partitions are pruned on it. The
record policies add the caller's reach; nothing here decides it.

The three W1 orderings are NOT NULL columns, each with an index
`(tenant_id, object_id, <column>, id)`, so a page is the `values` phase of
`keyset_phases` alone; `name` orders under `COLLATE "vi-VN-x-icu"`, the
collation its index carries (R8.2). `count=exact` counts a `LIMIT cap + 1`
subquery under the same scope and policies, so it costs at most cap rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import NullType

from dw_kernel.filters import ListQuery, compile_filter
from dw_kernel.pagination import Phase
from dw_platform.adapters.persistence.keyset import KeysetPhase, keyset_phases
from dw_studio.records.adapters.tables import records
from dw_studio.records.application.ports import AppliedObject

COLLATION: Final = "vi-VN-x-icu"
TENANT_PARAM: Final = "tenant"
OBJECT_PARAM: Final = "object"

ROW_COLUMNS: Final = (
    records.c.id,
    records.c.object_id,
    records.c.workspace_id,
    records.c.owner_kind,
    records.c.owner_id,
    records.c.name,
    records.c.version,
    records.c.created_at,
    records.c.created_by,
    records.c.updated_at,
    records.c.updated_by,
    records.c.deleted_at,
    records.c.deleted_by,
    records.c.data,
)


def slot_columns(obj: AppliedObject) -> list[sa.Column[Any]]:
    """The slot columns the object's fields hold, sorted."""
    slots = sorted(
        {s.slot for s in obj.storage.values() if s.storage_kind == "slot" and s.slot is not None}
    )
    return [records.c[slot] for slot in slots]


@dataclass(frozen=True, slots=True)
class CompiledPage:
    """A page's statement and the phases `keyset_rows` runs it in."""

    statement: sa.Select[Any]
    phases: tuple[KeysetPhase, ...]


class RecordQueryCompiler:
    """The statements of one object's list, for one bound company."""

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id

    def _scoped(self, statement: sa.Select[Any], obj: AppliedObject, query: ListQuery) -> Any:
        statement = statement.where(
            records.c.tenant_id == sa.bindparam(TENANT_PARAM, self.tenant_id, type_=UUID),
            records.c.object_id == sa.bindparam(OBJECT_PARAM, obj.object_id, type_=UUID),
            records.c.deleted_at.is_(None),
        )
        if query.filter is not None:
            compiled = compile_filter(query.filter)
            # One parenthesised term beside the scope, never in place of it.
            # Untyped binds: PostgreSQL types each from the column it meets (a
            # `str` typed here would be cast to varchar, which no uuid takes).
            binds = [sa.bindparam(k, v, type_=NullType()) for k, v in compiled.params.items()]
            statement = statement.where(sa.text(compiled.sql).bindparams(*binds))
        return statement

    def page(self, obj: AppliedObject, query: ListQuery) -> CompiledPage:
        sort: sa.ColumnElement[Any] = records.c[query.order.field.column]
        if query.order.field.column == "name":
            sort = sort.collate(COLLATION)
        statement = self._scoped(sa.select(*ROW_COLUMNS, *slot_columns(obj)), obj, query)
        phases = keyset_phases(
            sort, records.c.id, descending=query.order.descending, after=query.page.after
        )
        # NOT NULL: the values phase is the whole list (a NULLs cursor, which
        # no page of these columns mints, reads nothing).
        return CompiledPage(statement, tuple(p for p in phases if p.phase is Phase.VALUES))

    def count(self, obj: AppliedObject, query: ListQuery, cap: int) -> sa.Select[Any]:
        matches = self._scoped(sa.select(sa.literal(1)), obj, query).limit(cap + 1)
        return sa.select(sa.func.count()).select_from(matches.subquery("matches"))
