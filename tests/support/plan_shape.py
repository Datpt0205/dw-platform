"""The plan-shape check: a paged statement that no index carries fails CI.

app-standards R6 (ADR-0108 points 2 and 3; `CLAUDE.md` "Data model rules").
A keyset page is only cheap if an index leading with `tenant_id` hands rows
over in the page's order; without one, page 50 sorts the whole match set and
costs what page 1 costs, and nothing a functional test asserts can see it.
So the check asks Postgres, not the source (`failure-modes.md` #0):

1. The statements are the real ones: :func:`capture` records what the
   repository sent, through `before_cursor_execute`, while it ran under
   `dw_app` with the tenant bound, on a first page and on a page with a cursor.
2. Each is planned with `EXPLAIN (FORMAT JSON)` under the same role and
   settings, with `SET LOCAL enable_seqscan = off`, so a small test table
   cannot pass by being small enough to scan.
3. :func:`plan_problems` names what is wrong, per statement:
   - a declared column (`tenant_id`, which RLS adds, and the statement's own
     predicate columns; never the `workspace_id OR app.workspace_scope` arm of
     RLS) in no `Index Cond` or `Recheck Cond` of the paged table's scans;
   - a scan of the paged table that is no index scan, or whose index does not
     lead with `tenant_id` (a joined table's look-up and an RLS subplan do not
     count, R6.1);
   - a `Sort` or `Incremental Sort` on a sort key: the index did not deliver
     the order.

The registry of what is checked is :data:`REGISTERED`, keyed by operation; the
app-build test holds it against every operation of `app.openapi()` that takes a
cursor (R6.3), and the integration test runs exactly its entries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

# Every operation whose page the check plans, with the table it pages
# (R6.2). Frozen: a new paged route joins here and in the integration test.
REGISTERED: Final[Mapping[tuple[str, str], str]] = {
    ("GET", "/api/v1/approvals"): "platform.approval_requests",
    ("GET", "/api/v1/audit/events"): "platform.audit_events",
    ("GET", "/api/v1/digital-workers"): "platform.digital_workers",
    ("GET", "/api/v1/work-items"): "platform.work_items",
    ("GET", "/api/v1/feedback"): "platform.feedback",
    ("GET", "/api/v1/knowledge/documents"): "knowledge.documents",
    ("GET", "/api/v1/memory/items"): "memory.items",
}

# Operations that take a cursor and are not planned here, each with why.
# Frozen like the registry; a name without a reason, or one that no longer
# names an operation, fails the app-build test.
EXEMPT: Final[Mapping[tuple[str, str], str]] = {}

_SCANS: Final = frozenset({"Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Seq Scan"})
_SORTS: Final = frozenset({"Sort", "Incremental Sort"})


@dataclass(frozen=True)
class Captured:
    statement: str
    parameters: Any


@contextmanager
def capture(engine: AsyncEngine) -> Iterator[list[Captured]]:
    """Every statement ``engine`` sends while the block runs, as sent."""
    seen: list[Captured] = []

    def record(
        _conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, _many: bool
    ) -> None:
        seen.append(Captured(statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


def paged(captured: Sequence[Captured], table: str) -> list[Captured]:
    """The statements that read a page of ``table``: a SELECT from it with a LIMIT."""
    pattern = re.compile(rf"\bFROM\s+{re.escape(table)}\b", re.IGNORECASE)
    return [
        c
        for c in captured
        if c.statement.lstrip().upper().startswith("SELECT")
        and pattern.search(c.statement)
        and re.search(r"\bLIMIT\b", c.statement, re.IGNORECASE)
    ]


@dataclass(frozen=True)
class Scope:
    """The settings `tenant_session` binds, so RLS plans as it runs."""

    tenant_id: str
    workspace_id: str
    user_id: str


async def bind(conn: AsyncConnection, scope: Scope) -> None:
    """Inside an open transaction: the tenant's settings, and no sequential scan
    or sort unless nothing else can answer."""
    await conn.execute(
        sa.text(
            "SELECT set_config('app.tenant_id', :t, true),"
            " set_config('app.workspace_id', :w, true), set_config('app.user_id', :u, true)"
        ),
        {"t": scope.tenant_id, "w": scope.workspace_id, "u": scope.user_id},
    )
    await conn.execute(sa.text("SET LOCAL enable_seqscan = off"))
    # Priced out, not forbidden, like the sequential scan: on a test table of a
    # few rows the planner rightly sorts three rows rather than walk an index,
    # and the question here is whether an index CAN hand the page over in
    # order. Without one the Sort stays in the plan, and the check fails it.
    await conn.execute(sa.text("SET LOCAL enable_sort = off"))


async def explain(conn: AsyncConnection, captured: Captured) -> dict[str, Any]:
    """The plan of one captured statement, on ``conn`` as it is bound."""
    result = await conn.exec_driver_sql(
        "EXPLAIN (FORMAT JSON) " + captured.statement, captured.parameters
    )
    raw = result.scalar_one()
    document = json.loads(raw) if isinstance(raw, str) else raw
    plan: dict[str, Any] = document[0]["Plan"]
    return plan


@dataclass(frozen=True)
class Expectation:
    """What one paged statement must get from its index.

    ``exempt_indexes`` names an index whose scan is not held to the rule, with
    why: one read of rows RLS lets every tenant see (global documents), which
    no index can lead with a tenant for. A scan through any other index is."""

    table: str
    predicates: tuple[str, ...]
    sort_keys: tuple[str, ...]
    exempt_indexes: Mapping[str, str] = field(default_factory=dict)


def _nodes(plan: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


_BITMAP: Final = frozenset({"Bitmap Index Scan", "BitmapAnd", "BitmapOr"})


def _bitmap_children(scan: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """The index scans feeding a bitmap heap scan; never a SubPlan it evaluates
    (a correlated count over another table hangs off the same node)."""
    for child in scan.get("Plans", []):
        if child.get("Node Type") in _BITMAP:
            yield child
            yield from _bitmap_children(child)


async def _partitions(conn: AsyncConnection, table: str) -> set[str]:
    """``table``'s own name and those of its partitions, unqualified."""
    rows = await conn.execute(
        sa.text(
            "SELECT c.relname FROM pg_class c WHERE c.oid = CAST(:t AS regclass)"
            " UNION SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
            " WHERE i.inhparent = CAST(:t AS regclass)"
        ),
        {"t": table},
    )
    return {row[0] for row in rows}


async def _leading_column(conn: AsyncConnection, index: str) -> str | None:
    return await conn.scalar(
        sa.text(
            "SELECT pg_get_indexdef(c.oid, 1, true) FROM pg_class c"
            " WHERE c.relname = :i AND c.relkind IN ('i', 'I') LIMIT 1"
        ),
        {"i": index},
    )


def _mentions(text: str, column: str) -> bool:
    return re.search(rf"\b{re.escape(column)}\b", text) is not None


def _scan_indexes(scan: Mapping[str, Any]) -> list[str]:
    found = [scan.get("Index Name")] + [child.get("Index Name") for child in _bitmap_children(scan)]
    return [name for name in found if name]


def _scan_conditions(scan: Mapping[str, Any]) -> str:
    conditions = [str(scan.get(key, "")) for key in ("Index Cond", "Recheck Cond")]
    conditions.extend(str(child.get("Index Cond", "")) for child in _bitmap_children(scan))
    return " ".join(conditions)


async def plan_problems(
    conn: AsyncConnection, plan: Mapping[str, Any], expected: Expectation
) -> list[str]:
    """What ``plan`` gets wrong against ``expected``; empty when nothing."""
    names = await _partitions(conn, expected.table)
    problems: list[str] = []
    scans = [
        node
        for node in _nodes(plan)
        if node.get("Node Type") in _SCANS and node.get("Relation Name") in names
    ]
    if not scans:
        problems.append(f"no scan of {expected.table} in the plan")
    for scan in scans:
        relation = scan["Relation Name"]
        if scan["Node Type"] == "Seq Scan":
            problems.append(f"{relation} is read by a sequential scan")
            continue
        indexes = _scan_indexes(scan)
        if indexes and all(index in expected.exempt_indexes for index in indexes):
            continue
        for index in indexes:
            leading = await _leading_column(conn, index)
            if leading != "tenant_id":
                problems.append(f"index {index} leads with {leading}, not tenant_id")
        conditions = _scan_conditions(scan)
        for column in ("tenant_id", *expected.predicates):
            if not _mentions(conditions, column):
                problems.append(
                    f"column {column} of {relation} is in no Index Cond or Recheck Cond"
                )
    for node in _nodes(plan):
        if node.get("Node Type") in _SORTS:
            keys = " ".join(node.get("Sort Key", []))
            for column in expected.sort_keys:
                if _mentions(keys, column):
                    problems.append(f"a {node['Node Type']} node sorts on {column}")
    return problems


async def problems_of(
    admin_url: str,
    scope: Scope,
    statements: Sequence[Captured],
    expected: Expectation,
    *,
    ddl: Sequence[str] = (),
) -> list[str]:
    """Plan ``statements`` as `dw_app` bound to ``scope``, after ``ddl`` (an
    index dropped or added for a test that shows the check going red), all in
    one transaction rolled back after. ``admin_url`` is the test database as
    its superuser, the one role that may both change the schema and become
    `dw_app` in the same transaction."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    found: list[str] = []
    engine = create_async_engine(admin_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn, conn.begin() as tx:
            for statement in ddl:
                await conn.execute(sa.text(statement))
            await conn.execute(sa.text("SET LOCAL ROLE dw_app"))
            await bind(conn, scope)
            for captured in statements:
                plan = await explain(conn, captured)
                found.extend(
                    f"{problem} :: {captured.statement}"
                    for problem in await plan_problems(conn, plan, expected)
                )
            await tx.rollback()
    finally:
        await engine.dispose()
    return found


def admin_url_of(urls: Any) -> str:
    """The test database (``urls.app``'s) as the cluster's superuser."""
    return str(urls.admin).rsplit("/", 1)[0] + "/" + str(urls.app).rsplit("/", 1)[1]


# ------------------------------------------- statements from a schema (R6.4) --

_SAMPLES: Final[Mapping[str, object]] = {
    "text": "m",
    "int": 1,
    "float": 1.0,
    "date": "2026-01-01",
    "datetime": "2026-01-01T00:00:00+00:00",
    "bool": True,
}


@dataclass(frozen=True)
class SchemaCase:
    """One statement a declared schema promises an index for."""

    label: str
    order_by: str | None
    filter: Mapping[str, object] | None
    # None for a first page; else the phase the cursor resumes in.
    phase: str | None
    sort_field: str
    filter_field: str | None


def schema_cases(schema: Any) -> list[SchemaCase]:
    """Every combination a `QuerySchema` declares (R6.4): each sortable field in
    each direction, on a first page and on a page resumed in each phase; and
    each operator of each filterable field, in the route's default order, on a
    first page and on a page with a cursor. Read from the schema, never a list
    of fixed statements, so a field or operator declared later is planned."""
    cases: list[SchemaCase] = []
    for field_ in schema.fields:
        if not field_.sortable:
            continue
        for direction in ("asc", "desc"):
            for phase in (None, "values", "nulls"):
                cases.append(
                    SchemaCase(
                        f"order_by {field_.name} {direction}, {phase or 'first'} page",
                        f"{field_.name} {direction}",
                        None,
                        phase,
                        field_.name,
                        None,
                    )
                )
    default_field, _ = schema.default_order
    for field_ in schema.fields:
        if not field_.filterable:
            continue
        sample = _SAMPLES[field_.type.value]
        for operator in sorted(field_.operators):
            operand = [sample] if operator == "$in" else sample
            for phase in (None, "values"):
                cases.append(
                    SchemaCase(
                        f"{field_.name} {operator}, {phase or 'first'} page",
                        None,
                        {field_.name: {operator: operand}},
                        phase,
                        default_field,
                        field_.name,
                    )
                )
    return cases


def sample_value(type_name: str) -> object:
    return _SAMPLES[type_name]
