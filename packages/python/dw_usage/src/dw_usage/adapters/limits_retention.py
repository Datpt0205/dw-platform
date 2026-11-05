"""The `retention_limits` lane: past periods' counters and long-closed leases
go (usage-and-limits R5.7; ADR-0121 decision 5; failure-modes #6).

Both terms come from the pinned retention fragments, `platform.budget_counters`
(395 days after a period ends) and `platform.budget_leases` (30 days after a
lease closes), never from a number in this module. A store with no fragment,
or one nobody decided (`days: null`), is a configuration error: logged, and
nothing of that store is deleted. A decided term not yet `enforced` deletes
nothing either.

A closed lease is kept while its root run is still waiting: what a run spent
across its waits is the sum of its leases (gate 4/11/2026), read when it goes
on. That needs the run's row, so leases go one company at a time under its own
tenant; the counters go in one statement under the drain, the only reader of
`worker_drain_budget_counters_delete`. Operational rows, not a person's
records: counts are logged, no audit row (`CLAUDE.md`, Agent and tool rules).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.retention_policy import RetentionPolicy

__all__ = ["BUDGET_COUNTERS", "BUDGET_LEASES", "SqlLimitsRetention"]

_LOG = logging.getLogger("dw_usage.limits_retention")

BUDGET_COUNTERS: Final = "platform.budget_counters"
BUDGET_LEASES: Final = "platform.budget_leases"

_SET_TENANT = sa.text("SELECT set_config('app.tenant_id', :t, true)")
_SET_DRAIN = sa.text("SELECT set_config('app.worker_drain', 'on', true)")
_PURGE_COUNTERS = sa.text("DELETE FROM platform.budget_counters WHERE window_end < :cutoff")
_TENANTS_WITH_OLD_LEASES = sa.text(
    "SELECT DISTINCT tenant_id FROM platform.budget_leases"
    " WHERE state = 'closed' AND closed_at < :cutoff"
)
_PURGE_LEASES = sa.text(
    "DELETE FROM platform.budget_leases l"
    " WHERE l.state = 'closed' AND l.closed_at < :cutoff"
    " AND NOT EXISTS ("
    "   SELECT 1 FROM platform.worker_runs r"
    "   WHERE r.id = l.root_run_id"
    "     AND r.status NOT IN ('completed', 'failed', 'cancelled', 'dead_lettered')"
    " )"
)


@dataclass(frozen=True)
class SqlLimitsRetention:
    """Implements the worker's `RetentionPrunePort` for the two limit tables."""

    session_factory: async_sessionmaker[AsyncSession]
    policy: RetentionPolicy
    clock: UtcClock

    async def prune(self) -> None:
        """One pass of the lane: both stores, each on its own term."""
        await self.purge_counters()
        await self.purge_leases()

    async def purge_counters(self) -> None:
        """The purger of `platform.budget_counters` (the worker's registry entry)."""
        cutoff = self._cutoff(BUDGET_COUNTERS, self.clock.now())
        if cutoff is None:
            return
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            removed = await session.execute(_PURGE_COUNTERS, {"cutoff": cutoff})
        _LOG.info("budget counters pruned", extra={"deleted": getattr(removed, "rowcount", 0)})

    async def purge_leases(self) -> None:
        """The purger of `platform.budget_leases` (the worker's registry entry)."""
        cutoff = self._cutoff(BUDGET_LEASES, self.clock.now())
        if cutoff is None:
            return
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            tenants = list(
                (await session.scalars(_TENANTS_WITH_OLD_LEASES, {"cutoff": cutoff})).all()
            )
        gone = 0
        for tenant_id in tenants:
            async with self.session_factory() as session, session.begin():
                await session.execute(_SET_TENANT, {"t": str(tenant_id)})
                removed = await session.execute(_PURGE_LEASES, {"cutoff": cutoff})
                gone += getattr(removed, "rowcount", 0)
        _LOG.info("budget leases pruned", extra={"deleted": gone})

    def _cutoff(self, store: str, now: datetime) -> datetime | None:
        if self.policy.term(store) is None:
            # No fragment, or nobody decided: nothing is purged on a guess.
            _LOG.error(
                "retention configuration error: no decided term for %s; nothing deleted", store
            )
            return None
        return self.policy.store_cutoff(store, now=now)
