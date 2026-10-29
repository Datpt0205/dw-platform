"""Tenant offboarding: export then purge every tenant-scoped table.

Discovered from the catalog rather than a hand-maintained list — the same
query `test_migration_and_rls.py`'s own RLS-coverage test already uses
(`pg_policies` filtered to `tenant_isolation_%`), so a table added by a later
migration — even from a bounded context this repo does not ship — is covered
the day its policy is created, not the day someone remembers to add it here.
Hand-maintained lists of tenant tables have drifted in this repo before
(`platform.tenant_scoped_tables` in `tables.py` is dead code nobody reads,
found while building this).

`export_rows`/`purge_rows` run entirely under `app.tenant_id` for the one
tenant they target — the ordinary RLS mechanism every tenant-scoped query
already uses — plus `app.workspace_scope = 'tenant'`. A context may narrow its
tables by workspace as well (`tenant AND (workspace OR app.workspace_scope =
'tenant')`); under `app.tenant_id` alone such a table reads zero rows, so the
export would miss them silently, the purge would delete none, and the purge of
`platform.workspaces` would then CASCADE them away unexported. This class is the
only place that sets the scope, per transaction; `test_rls_coverage.py` keeps
every policy that reads it inside a tenant clause.

`claim_requested` is the one exception to running under one tenant: nothing
tells the worker which tenant has a request waiting until it asks, and asking is
itself the cross-tenant read `app.tenant_id` scoping exists to prevent — so
it runs under `app.worker_drain`, like the retention sweep, but only for that
one query. Migration `dd1db8ca43a2`.

What this does NOT do: touch Qdrant (either collection: knowledge chunks or
memory vectors) or object storage. Both live behind ports
this package may not import (import-linter's "Vector/object-storage SDKs only
inside knowledge adapters"). The worker's offboarding lane — the composition
root, which may import every concrete adapter — orchestrates those
separately, calling `export_rows`/`purge_rows` here for the Postgres half.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = [
    "EXPORT_BATCH_ROWS",
    "EXPORT_EXCLUSIONS",
    "STUDIO_EXCLUSIONS",
    "ExportedTable",
    "OffboardingExclusion",
    "OffboardingPurgeStep",
    "OffboardingPurgeSteps",
    "OffboardingRefusedError",
    "SqlTenantOffboarding",
    "order_purge_steps",
]

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
# Every workspace of the one tenant, for this transaction only (`true`): a pooled
# connection must not carry the scope into whoever borrows it next.
_SET_TENANT_ALL_WORKSPACES = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    "       set_config('app.workspace_scope', 'tenant', true)"
)
_SET_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")

# How long an in-progress request goes untouched before `claim_requested`
# treats it as abandoned by a dead worker rather than owned by a live one.
# Comfortably above how long one tenant's export+purge should ever take.
_STALE_CLAIM_MINUTES = 30

# Joined from `pg_policy` and privileges asked by oid, not by name through
# the `pg_policies` view: the planner is free to evaluate a name-based
# `has_table_privilege` on every `pg_class` row before the join narrows them
# to policies, and a name in `pg_toast` is "permission denied for schema" to
# dw_app. Measured: adding three tables changed the plan and this query
# failed on every call. An oid needs no schema lookup.
_CATALOG_COLUMNS = (
    "SELECT DISTINCT n.nspname AS schemaname, c.relname AS tablename"
    " FROM pg_policy pol"
    " JOIN pg_class c ON c.oid = pol.polrelid"
    " JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE pol.polname LIKE 'tenant_isolation_%'"
    # A partition is read through its parent: listing both exported every
    # partitioned row twice (R11.1). Not left to the revoke of studio-skeleton/01
    # alone, which removes dw_app's SELECT on partitions today: a grant restored
    # by mistake would quietly double the bundle again.
    "   AND NOT c.relispartition"
    "   AND has_table_privilege('dw_app', c.oid, 'SELECT')"
    # platform.tenants carries a tenant_isolation_% policy (it IS the tenant,
    # keyed on `id`) but no `tenant_id` column of its own — the generic
    # `WHERE tenant_id = :t` this class runs would fail on it with "column
    # does not exist", found while writing test_offboarding.py. Filtering on
    # the column actually existing excludes it (and anything shaped like it
    # later) without a hand-maintained exception list.
    "   AND EXISTS ("
    "     SELECT 1 FROM information_schema.columns ic"
    "     WHERE ic.table_schema = n.nspname AND ic.table_name = c.relname"
    "       AND ic.column_name = 'tenant_id'"
    "   )"
)

# Every table this class may SELECT from a tenant to export it.
_CATALOG_EXPORTABLE = text(_CATALOG_COLUMNS + " ORDER BY schemaname, tablename")

# Only the ones `dw_app` may also DELETE from. `platform.audit_events` is
# exportable but not this: `0001_platform_grants.sql` revokes UPDATE/DELETE
# from `dw_app` there on purpose (append-only; the audit term is its retention
# fragment's, `retention.d/platform.audit_events.yaml`, not offboarding's to
# shorten). Found
# by running this against a real database rather than assumed — the same
# revoke could apply to a table added later, and asking `has_table_privilege`
# instead of hand-naming `audit_events` catches that one too.
_CATALOG_PURGEABLE = text(
    _CATALOG_COLUMNS + "   AND has_table_privilege('dw_app', c.oid, 'DELETE')"
    " ORDER BY schemaname, tablename"
)

# Every foreign key the purge order can depend on, from the running catalog
# (R11.4): the order is derived from these, never written down by hand. A NO
# ACTION constraint deferred to commit does not stop a delete inside the
# transaction, so it orders nothing; RESTRICT is checked at once even when
# deferrable, so it always orders.
_FOREIGN_KEYS = text(
    "SELECT k.conname,"
    "       rn.nspname || '.' || r.relname AS referencing,"
    "       dn.nspname || '.' || d.relname AS referenced,"
    "       k.confdeltype::text AS confdeltype"
    " FROM pg_constraint k"
    " JOIN pg_class r ON r.oid = k.conrelid"
    " JOIN pg_namespace rn ON rn.oid = r.relnamespace"
    " JOIN pg_class d ON d.oid = k.confrelid"
    " JOIN pg_namespace dn ON dn.oid = d.relnamespace"
    " WHERE k.contype = 'f' AND NOT r.relispartition AND NOT d.relispartition"
    "   AND NOT (k.confdeltype = 'a' AND k.condeferrable AND k.condeferred)"
)

# The primary key columns of one table, in key order: the keyset an export
# pages on (R11.2).
_PRIMARY_KEY = text(
    "SELECT a.attname FROM pg_index i"
    " JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true"
    " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum"
    " WHERE i.indrelid = CAST(:relation AS regclass) AND i.indisprimary"
    " ORDER BY k.ord"
)

# Rows per export statement (R11.2).
EXPORT_BATCH_ROWS = 1000

_BLOCKING = frozenset({"r", "a"})  # RESTRICT, NO ACTION
_CASCADING = "c"

# This row IS the job — purging it out from under the worker running this
# pass is not a table this pass owns clearing.
_NEVER_PURGE = frozenset({("platform", "tenant_offboarding_requests")})


@dataclass(frozen=True)
class OffboardingExclusion:
    """How a tenant table this class does not DELETE from loses its rows, or why
    it keeps them: exactly one of the three, each checked against the running
    catalog by `test_offboarding_coverage.py` (studio-skeleton R4.4).

    - `cascade_from`: the `schema.table` it cascades from, which this class deletes;
    - `function`: the `schema.fn` step that deletes it;
    - `kept`: its own `schema.table` key in the retention fragments, with a term
      that is enforced.
    """

    reason: str
    cascade_from: str | None = None
    function: str | None = None
    kept: str | None = None

    def __post_init__(self) -> None:
        ways = [way for way in (self.cascade_from, self.function, self.kept) if way]
        if len(ways) != 1:
            raise ValueError("an exclusion names exactly one of cascade_from, function, kept")
        if not self.reason.strip():
            raise ValueError("an exclusion carries a reason")


# Tables of `studio`, and tenant tables of `platform` added after studio-skeleton
# ticket 01, that `purge_rows` does not delete from, keyed `schema.table`. This
# class does not read either mapping; the coverage test does, and fails a tenant
# table that is neither purged nor listed, a row the catalog does not confirm,
# and a row for a table that is gone or now handled (R4.1, R4.3-R4.5).
STUDIO_EXCLUSIONS: Mapping[str, OffboardingExclusion] = MappingProxyType({})

# Tenant tables `export_rows` does not export, with why the bundle goes without
# them: apart from STUDIO_EXCLUSIONS, because being deleted another way says
# nothing about being handed back to the customer first (R4.1).
EXPORT_EXCLUSIONS: Mapping[str, str] = MappingProxyType({})

# A real schema/table identifier from Postgres's own catalog never needs
# quoting and never contains anything this does not match. Checked, not
# assumed: the alternative is string-formatting a table name from a query
# result straight into SQL, and this is what stands between that and being
# indistinguishable from injection.
_SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _quoted(schema: str, table: str) -> str:
    for identifier in (schema, table):
        if not _SAFE_IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"refusing an unsafe catalog identifier: {identifier!r}")
    return f'"{schema}"."{table}"'


@dataclass(frozen=True)
class ExportedTable:
    """One batch of one table's rows: at most `EXPORT_BATCH_ROWS`, and a table
    arrives as consecutive batches."""

    schema: str
    table: str
    rows: list[dict[str, Any]]


class OffboardingRefusedError(Exception):
    """The pass refuses before its first export or delete (R11.5, R11.7): the
    tenant stays `offboarding`, and the message names what has to be fixed."""


PurgeRun = Callable[[AsyncSession, UUID], Awaitable[None]]


@dataclass(frozen=True)
class OffboardingPurgeStep:
    """A deleting step of the lane (R11.4): `tables` are the `schema.table`
    names it deletes from, and `run` deletes only the rows of the tenant it is
    handed (R11.6), inside the purge transaction."""

    name: str
    tables: frozenset[str]
    run: PurgeRun


@dataclass
class OffboardingPurgeSteps:
    """The registry of deleting steps, built at the worker's composition root.

    A context that deletes its tables its own way registers a step here rather
    than editing this module; every purgeable table no step declares gets a
    default step. The order is never declared: `purge_rows` derives it from
    the catalog's foreign keys.
    """

    _steps: dict[str, OffboardingPurgeStep] = field(default_factory=dict)

    def register(self, step: OffboardingPurgeStep) -> None:
        if step.name in self._steps:
            raise ValueError(f"purge step already registered: {step.name}")
        for other in self._steps.values():
            shared = step.tables & other.tables
            if shared:
                raise ValueError(
                    f"purge steps {other.name} and {step.name} both declare {sorted(shared)}"
                )
        self._steps[step.name] = step

    def all(self) -> list[OffboardingPurgeStep]:
        return list(self._steps.values())


def _default_step(qualified: str) -> OffboardingPurgeStep:
    schema, table = qualified.split(".", 1)
    statement = text(f"DELETE FROM {_quoted(schema, table)} WHERE tenant_id = :t")  # nosec B608

    async def run(session: AsyncSession, tenant_id: UUID) -> None:
        await session.execute(statement, {"t": str(tenant_id)})

    return OffboardingPurgeStep(name=qualified, tables=frozenset({qualified}), run=run)


def order_purge_steps(
    steps: Sequence[OffboardingPurgeStep], foreign_keys: Sequence[Any]
) -> list[OffboardingPurgeStep]:
    """The steps in the order the catalog's RESTRICT and NO ACTION edges demand.

    A table no step declares but that loses rows through CASCADE from a step's
    table carries its edges to that step. Edges inside one step order nothing.
    Unconnected steps keep name order, so two runs agree. A cycle refuses
    before any delete, naming its foreign keys (R11.5).
    """
    owner: dict[str, str] = {}
    for step in steps:
        for table in step.tables:
            owner[table] = step.name
    reached: dict[str, set[str]] = {s.name: set(s.tables) for s in steps}
    changed = True
    while changed:
        changed = False
        for fk in foreign_keys:
            if fk.confdeltype != _CASCADING or fk.referencing in owner:
                continue
            for tables in reached.values():
                if fk.referenced in tables and fk.referencing not in tables:
                    tables.add(fk.referencing)
                    changed = True

    deleters: dict[str, set[str]] = {}
    for name, tables in reached.items():
        for table in tables:
            deleters.setdefault(table, set()).add(name)

    before: dict[str, set[str]] = {s.name: set() for s in steps}
    edge_names: dict[tuple[str, str], str] = {}
    for fk in foreign_keys:
        if fk.confdeltype not in _BLOCKING:
            continue
        target = owner.get(fk.referenced)
        if target is None:
            continue
        for source in deleters.get(fk.referencing, set()):
            if source != target:
                before[target].add(source)
                edge_names.setdefault((source, target), fk.conname)

    ordered: list[OffboardingPurgeStep] = []
    pending = {s.name: s for s in steps}
    while pending:
        ready = sorted(name for name in pending if not (before[name] & pending.keys()))
        if not ready:
            cycle = sorted(
                conname
                for (source, target), conname in edge_names.items()
                if source in pending and target in pending
            )
            raise OffboardingRefusedError(f"purge steps form a cycle through {cycle}")
        for name in ready:
            ordered.append(pending.pop(name))
    return ordered


@dataclass(frozen=True)
class SqlTenantOffboarding:
    session_factory: async_sessionmaker[AsyncSession]
    steps: OffboardingPurgeSteps = field(default_factory=OffboardingPurgeSteps)

    async def _exportable_tables(self, session: AsyncSession) -> list[tuple[str, str]]:
        rows = (await session.execute(_CATALOG_EXPORTABLE)).all()
        return [
            (row.schemaname, row.tablename)
            for row in rows
            if (row.schemaname, row.tablename) not in _NEVER_PURGE
        ]

    async def _purgeable_tables(self, session: AsyncSession) -> list[tuple[str, str]]:
        rows = (await session.execute(_CATALOG_PURGEABLE)).all()
        return [
            (row.schemaname, row.tablename)
            for row in rows
            if (row.schemaname, row.tablename) not in _NEVER_PURGE
        ]

    async def _primary_key(self, session: AsyncSession, schema: str, table: str) -> list[str]:
        columns = list(
            (await session.execute(_PRIMARY_KEY, {"relation": _quoted(schema, table)})).scalars()
        )
        unsafe = [column for column in columns if not _SAFE_IDENTIFIER.fullmatch(column)]
        if unsafe:
            # Dropping a column would page on part of the key and skip rows.
            raise OffboardingRefusedError(
                f"{schema}.{table} has key columns {unsafe} it cannot page on"
            )
        return columns

    async def export_rows(self, tenant_id: UUID) -> AsyncIterator[ExportedTable]:
        """Every exportable row of the tenant, once, in batches of at most
        `EXPORT_BATCH_ROWS` read by keyset on the primary key (R11.1, R11.2).

        One transaction for the whole pass, as before. Refuses before the first
        batch when a table has no primary key or a foreign key would block the
        purge (R11.7): a bundle missing a table, or a purge that stops halfway,
        is worse than a pass that never starts.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT_ALL_WORKSPACES, {"tenant_id": str(tenant_id)})
            await self._refuse_blocked(session, tenant_id)
            for schema, table in await self._exportable_tables(session):
                key = await self._primary_key(session, schema, table)
                if not key:
                    raise OffboardingRefusedError(f"{schema}.{table} has no primary key")
                async for batch in self._batches(session, tenant_id, schema, table, key):
                    yield batch

    async def _batches(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        schema: str,
        table: str,
        key: list[str],
    ) -> AsyncIterator[ExportedTable]:
        columns = ", ".join(f'"{column}"' for column in key)
        after = ", ".join(f":k{i}" for i in range(len(key)))
        relation = _quoted(schema, table)
        # B608 is a false positive here: the identifiers come from the catalog
        # (`_CATALOG_*`, `_PRIMARY_KEY`), never from a caller, and are quoted;
        # values are bind parameters. Same for the DELETE of `_default_step`.
        first = text(
            f"SELECT * FROM {relation} WHERE tenant_id = :t"  # nosec B608
            f" ORDER BY {columns} LIMIT {EXPORT_BATCH_ROWS}"
        )
        following = text(
            f"SELECT * FROM {relation} WHERE tenant_id = :t"  # nosec B608
            f" AND ({columns}) > ({after}) ORDER BY {columns} LIMIT {EXPORT_BATCH_ROWS}"
        )
        last: dict[str, Any] | None = None
        while True:
            params: dict[str, Any] = {"t": str(tenant_id)}
            if last is not None:
                params |= {f"k{i}": last[column] for i, column in enumerate(key)}
            rows = [
                dict(row._mapping)
                for row in await session.execute(first if last is None else following, params)
            ]
            if not rows:
                return
            yield ExportedTable(schema=schema, table=table, rows=rows)
            if len(rows) < EXPORT_BATCH_ROWS:
                return
            last = rows[-1]

    async def _steps_for(self, session: AsyncSession) -> list[OffboardingPurgeStep]:
        declared = {table for step in self.steps.all() for table in step.tables}
        defaults = [
            _default_step(f"{schema}.{table}")
            for schema, table in await self._purgeable_tables(session)
            if f"{schema}.{table}" not in declared
        ]
        return [*self.steps.all(), *defaults]

    async def _ordered_steps(self, session: AsyncSession) -> list[OffboardingPurgeStep]:
        foreign_keys = (await session.execute(_FOREIGN_KEYS)).all()
        return order_purge_steps(await self._steps_for(session), foreign_keys)

    async def _refuse_blocked(self, session: AsyncSession, tenant_id: UUID) -> None:
        """R11.7: a table holding the tenant's rows that no step deletes, and
        no CASCADE reaches, yet RESTRICTs a step's table, would stop the purge
        halfway with a raw foreign-key error. Named here, before anything moves.
        """
        steps = await self._steps_for(session)
        foreign_keys = (await session.execute(_FOREIGN_KEYS)).all()
        order_purge_steps(steps, foreign_keys)  # a cycle refuses here too (R11.5)
        deleted = {table for step in steps for table in step.tables}
        changed = True
        while changed:
            changed = False
            for fk in foreign_keys:
                if (
                    fk.confdeltype == _CASCADING
                    and fk.referenced in deleted
                    and fk.referencing not in deleted
                ):
                    deleted.add(fk.referencing)
                    changed = True
        exportable = {
            f"{schema}.{table}" for schema, table in await self._exportable_tables(session)
        }
        for fk in foreign_keys:
            if fk.confdeltype not in _BLOCKING or fk.referenced not in deleted:
                continue
            if fk.referencing in deleted or fk.referencing not in exportable:
                continue
            schema, table = fk.referencing.split(".", 1)
            held = await session.scalar(
                text(f"SELECT 1 FROM {_quoted(schema, table)} WHERE tenant_id = :t LIMIT 1"),  # nosec B608
                {"t": str(tenant_id)},
            )
            if held:
                raise OffboardingRefusedError(
                    f"{fk.referencing} keeps the tenant's rows and {fk.conname} blocks the purge"
                    f" of {fk.referenced}"
                )

    async def purge_order(self, session: AsyncSession) -> tuple[str, ...]:
        """The order `purge_rows` deletes in: each step's name, then the tables
        it declares.

        The one answer to that question: `purge_rows` walks it and
        `test_offboarding_coverage.py` reads it to check every RESTRICT and NO
        ACTION edge the running catalog declares (studio-skeleton R4.2).
        """
        entries: list[str] = []
        for step in await self._ordered_steps(session):
            for entry in (step.name, *sorted(step.tables)):
                if entry not in entries:
                    entries.append(entry)
        return tuple(entries)

    async def purge_rows(self, tenant_id: UUID) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT_ALL_WORKSPACES, {"tenant_id": str(tenant_id)})
            await self._refuse_blocked(session, tenant_id)
            steps = await self._ordered_steps(session)
            await self._record_purge_audit(session, tenant_id)
            for step in steps:
                await step.run(session, tenant_id)

    async def _record_purge_audit(self, session: AsyncSession, tenant_id: UUID) -> None:
        """A row in `platform.audit_events` for the one action here that
        cannot be undone — written first, in the same transaction as the
        first delete, so the record survives even if this pass crashes right
        after. Safe to be the first delete-adjacent write: `audit_events`
        is exportable but never purgeable (`dw_app` has no DELETE there — see
        `_CATALOG_PURGEABLE`), so this row outlives every other table this
        pass empties, for as long as its retention fragment's term says.

        `workspace_id`/`actor_id` are NOT NULL on `audit_events` and this
        pass has neither on hand directly, so both are looked up: any one of
        the tenant's own workspaces, and the operator who requested this
        (`tenant_offboarding_requests.requested_by`). If either is missing —
        a tenant with no workspace, or `purge_rows` called with no request on
        file, both edge cases rather than the real path (the worker lane
        always claims a request first) — the audit write is skipped rather
        than failing the purge: the deletion itself is the obligation this
        method exists to fulfil, and a missing "who asked" is a worse outcome
        to trade it against than a missing audit row for an edge case that
        should not occur.
        """
        workspace_id = await session.scalar(
            text("SELECT id FROM platform.workspaces WHERE tenant_id = :t LIMIT 1"),
            {"t": str(tenant_id)},
        )
        requested_by = await session.scalar(
            text(
                "SELECT requested_by FROM platform.tenant_offboarding_requests"
                " WHERE tenant_id = :t ORDER BY requested_at DESC LIMIT 1"
            ),
            {"t": str(tenant_id)},
        )
        if workspace_id is None or requested_by is None:
            return
        await session.execute(
            text(
                "INSERT INTO platform.audit_events"
                " (id, tenant_id, workspace_id, actor_id, action, resource_type,"
                "  resource_id, details, occurred_at)"
                " VALUES (gen_random_uuid(), :t, :w, :actor, 'tenant.offboarding.purged',"
                "  'tenant', :resource_id, CAST(:details AS jsonb), now())"
            ),
            {
                "t": str(tenant_id),
                "w": workspace_id,
                "actor": requested_by,
                # Same value as :t, textually — a separate bind name because
                # asyncpg infers one type per parameter name and tenant_id
                # (uuid) and resource_id (text) disagree on it.
                "resource_id": str(tenant_id),
                # The lane carries out the operator's recorded decision, so the
                # row stands in their name and names the lane (R11.3, ADR 0011).
                "details": '{"lane": "offboarding"}',
            },
        )

    async def claim_requested(self) -> list[UUID]:
        """Atomically move every claimable row to `'exporting'` and return the
        tenants claimed. `UPDATE ... RETURNING` rather than `SELECT` then
        `UPDATE`: two worker instances polling at once must not both claim the
        same request, and a single statement's row locks are what makes that
        true without an explicit lock clause.

        Claimable is `status='requested'` (new work) OR `status IN
        ('exporting','purging')` gone stale (`updated_at` older than the
        window below) — a worker that claimed a request and then died leaves
        it stuck there forever otherwise, since nothing else ever moves a
        request off `'requested'`. Safe to resume from either status: export
        only reads and overwrites its own key, purge deletes rows that may
        already be gone (a second `DELETE` of nothing is not an error), and
        `mark_status` overwrites the same row either way — every step this
        claim unblocks is naturally idempotent, so re-running one from the
        start is correct, not just tolerated.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            rows = await session.execute(
                text(
                    "UPDATE platform.tenant_offboarding_requests"
                    " SET status = 'exporting', updated_at = now()"
                    " WHERE status = 'requested'"
                    "    OR (status IN ('exporting', 'purging')"
                    "        AND updated_at < now() - make_interval(mins => :stale_minutes))"
                    " RETURNING tenant_id"
                ),
                {"stale_minutes": _STALE_CLAIM_MINUTES},
            )
            return [row.tenant_id for row in rows]

    async def mark_status(
        self,
        tenant_id: UUID,
        status: str,
        *,
        export_key: str | None = None,
        error: str | None = None,
    ) -> None:
        """Report progress back on the tenant's own request row. Runs under
        `app.tenant_id`, not the drain — by now the caller knows exactly which
        tenant this is, and every write from here on is an ordinary
        tenant-scoped one.
        """
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            await session.execute(
                text(
                    "UPDATE platform.tenant_offboarding_requests"
                    " SET status = :status,"
                    "     export_key = coalesce(:export_key, export_key),"
                    "     error = :error,"
                    "     updated_at = now()"
                    " WHERE tenant_id = :tenant_id"
                ),
                {
                    "status": status,
                    "export_key": export_key,
                    "error": error,
                    "tenant_id": str(tenant_id),
                },
            )
