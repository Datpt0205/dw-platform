"""The usage ledger, the company's time zone and the roll-up, in PostgreSQL.

Every statement runs under the company it is about, set per transaction from
the record or the caller's verified context (`set_config(..., true)`, so a
pooled connection carries nothing into the next one). The one exception is the
roll-up lane finding which companies have recent records: it sets
`app.worker_drain`, which only `worker_drain_usage_events` reads, and that
policy admits SELECT alone.

`dw_app` may INSERT and SELECT `platform.usage_events` and nothing else on it,
nothing at all on its partitions (migration `2354ad4d2e3c`), so this module
never names a partition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_usage.adapters.ledger_rows import insert_usage_event
from dw_usage.adapters.limits_sql import settle_into_lease
from dw_usage.application.ports import RunUsageRow, SummaryFilter, SummaryRow
from dw_usage.domain.events import UsageEvent

__all__ = [
    "SqlTenantTimezones",
    "SqlUsageLedger",
    "SqlUsageReads",
    "SqlUsageRollupStore",
]

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_SET_DRAIN = sa.text("SELECT set_config('app.worker_drain', 'on', true)")


@dataclass(frozen=True)
class SqlUsageLedger:
    """Implements `UsageLedgerPort`: one record per `(id, occurred_at)`.

    A record carrying a lease (a call its permit let through) moves that lease
    in the same transaction (`settle_into_lease`, usage-and-limits R5.11): the
    record and the settlement are one fact, written once. A record the reaper
    already wrote under the same key is not written again and settles nothing.
    """

    session_factory: async_sessionmaker[AsyncSession]

    async def settle(self, event: UsageEvent) -> bool:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(event.tenant_id)})
            written = await insert_usage_event(session, event)
            if written:
                await settle_into_lease(session, event)
        return written


@dataclass(frozen=True)
class SqlTenantTimezones:
    """Implements `TenantTimezonePort`, under the company's own tenant."""

    session_factory: async_sessionmaker[AsyncSession]

    async def timezone_of(self, tenant_id: UUID) -> str | None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            zone = await session.scalar(
                sa.text("SELECT timezone FROM platform.tenants WHERE id = :t"), {"t": tenant_id}
            )
        return str(zone) if zone else None


_RUN_USAGE = sa.text(
    "SELECT operation, provider, model, cost_source, count(*) AS calls,"
    "       coalesce(sum(input_tokens), 0) AS input_tokens,"
    "       coalesce(sum(output_tokens), 0) AS output_tokens,"
    "       coalesce(sum(cost_usd), 0) AS cost_usd"
    " FROM platform.usage_events"
    " WHERE tenant_id = :t AND run_id = :r"
    " GROUP BY operation, provider, model, cost_source"
    " ORDER BY operation, provider, model, cost_source"
)

_SUMS = (
    "sum(d.calls) AS calls, sum(d.input_tokens) AS input_tokens,"
    " sum(d.output_tokens) AS output_tokens, sum(d.cost_usd) AS cost_usd,"
    " sum(d.unpriced_calls) AS unpriced_calls, sum(d.estimated_calls) AS estimated_calls"
)
# One statement per grouping, each with fixed text; the filters are bind
# parameters that a NULL switches off.
_FILTERS = (
    " WHERE d.tenant_id = :t AND d.day >= :first AND d.day <= :last"
    "   AND (CAST(:w AS uuid) IS NULL OR d.workspace_id = CAST(:w AS uuid))"
    "   AND (CAST(:ak AS text) IS NULL OR d.artifact_kind = CAST(:ak AS text))"
    "   AND (CAST(:a AS uuid) IS NULL OR d.artifact_id = CAST(:a AS uuid))"
)
_SUMMARY: Final[dict[str, sa.TextClause]] = {
    "workspace": sa.text(
        "SELECT CAST(d.workspace_id AS text) AS key, NULL AS artifact_kind, w.name AS label, "  # nosec B608 - fixed text, values bound
        + _SUMS
        + " FROM platform.usage_daily d"
        " LEFT JOIN platform.workspaces w ON w.tenant_id = d.tenant_id AND w.id = d.workspace_id"
        + _FILTERS
        + " GROUP BY d.workspace_id, w.name ORDER BY sum(d.cost_usd) DESC, key NULLS LAST"
    ),
    "artifact": sa.text(
        "SELECT CAST(d.artifact_id AS text) AS key, d.artifact_kind, NULL AS label, "  # nosec B608 - fixed text, values bound
        + _SUMS
        + " FROM platform.usage_daily d"
        + _FILTERS
        + " GROUP BY d.artifact_kind, d.artifact_id"
        " ORDER BY sum(d.cost_usd) DESC, key NULLS LAST"
    ),
    "purpose": sa.text(
        "SELECT d.purpose AS key, NULL AS artifact_kind, NULL AS label, "  # nosec B608 - fixed text, values bound
        + _SUMS
        + " FROM platform.usage_daily d"
        + _FILTERS
        + " GROUP BY d.purpose ORDER BY sum(d.cost_usd) DESC, key"
    ),
}


@dataclass(frozen=True)
class SqlUsageReads:
    """Implements `UsageReadPort`, each read under the caller's company."""

    session_factory: async_sessionmaker[AsyncSession]

    async def run_usage(self, tenant_id: UUID, run_id: UUID) -> list[RunUsageRow]:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            rows = (await session.execute(_RUN_USAGE, {"t": tenant_id, "r": run_id})).all()
        return [
            RunUsageRow(
                operation=row.operation,
                provider=row.provider,
                model=row.model,
                cost_source=row.cost_source,
                calls=int(row.calls),
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                cost_usd=row.cost_usd,
            )
            for row in rows
        ]

    async def summary(self, tenant_id: UUID, query: SummaryFilter) -> list[SummaryRow]:
        params = {
            "t": tenant_id,
            "first": query.first_day,
            "last": query.last_day,
            "w": query.workspace_id,
            "ak": query.artifact_kind,
            "a": query.artifact_id,
        }
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            rows = (await session.execute(_SUMMARY[query.group_by], params)).all()
        return [
            SummaryRow(
                key=row.key,
                artifact_kind=row.artifact_kind,
                label=row.label,
                calls=int(row.calls),
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                cost_usd=row.cost_usd,
                unpriced_calls=int(row.unpriced_calls),
                estimated_calls=int(row.estimated_calls),
            )
            for row in rows
        ]


_TENANTS_SINCE = sa.text(
    "SELECT DISTINCT tenant_id FROM platform.usage_events WHERE occurred_at >= :since"
)
# Two replicas at once take turns on one company, so neither inserts a group
# the other is about to.
_LOCK = sa.text("SELECT pg_advisory_xact_lock(hashtext('platform.usage_rollup'), hashtext(:t))")
_CLEAR_DAY = sa.text("DELETE FROM platform.usage_daily WHERE tenant_id = :t AND day = :day")
_ROLL_DAY = sa.text(
    "INSERT INTO platform.usage_daily (tenant_id, workspace_id, day, artifact_kind,"
    "  artifact_id, user_id, provider, model, operation, purpose, payer, calls,"
    "  input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
    "  reasoning_tokens, cost_usd, unpriced_calls, estimated_calls, rolled_up_at)"
    # `user_id` stays NULL in W1: nothing groups by person (DO-51.2, M3).
    " SELECT e.tenant_id, e.workspace_id, :day, e.artifact_kind, e.artifact_id, NULL,"
    "  e.provider, e.model, e.operation, e.purpose, e.payer, count(*),"
    "  sum(e.input_tokens), sum(e.output_tokens), sum(e.cache_read_tokens),"
    "  sum(e.cache_write_tokens), sum(e.reasoning_tokens), coalesce(sum(e.cost_usd), 0),"
    "  count(*) FILTER (WHERE e.cost_source = 'unpriced'),"
    "  count(*) FILTER (WHERE e.cost_source = 'estimated'), :at"
    " FROM platform.usage_events e"
    " WHERE e.tenant_id = :t AND e.occurred_at >= :start AND e.occurred_at < :end"
    " GROUP BY e.tenant_id, e.workspace_id, e.artifact_kind, e.artifact_id, e.provider,"
    "  e.model, e.operation, e.purpose, e.payer"
)


@dataclass(frozen=True)
class SqlUsageRollupStore:
    """Implements `UsageRollupStorePort`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def tenants_with_usage_since(self, since: datetime) -> list[UUID]:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            rows = await session.scalars(_TENANTS_SINCE, {"since": since})
            return list(rows.all())

    async def recompute_day(
        self, tenant_id: UUID, day: date, start: datetime, end: datetime, at: datetime
    ) -> int:
        params = {"t": tenant_id, "day": day, "start": start, "end": end, "at": at}
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_TENANT, {"t": str(tenant_id)})
            await session.execute(_LOCK, {"t": str(tenant_id)})
            await session.execute(_CLEAR_DAY, {"t": tenant_id, "day": day})
            written = await session.execute(_ROLL_DAY, params)
        return int(getattr(written, "rowcount", 0) or 0)
