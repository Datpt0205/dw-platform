"""`PlanCatalogPort` over `platform.plan_limits`, and its in-process cache.

The only module that builds a `PlanLimits` (usage-and-limits R1.1): every
limit a plan grants is read here, from the table, under `dw_app`, which may
SELECT it and nothing else (R1.3). The table is global, not a tenant's: it
has no RLS and no tenant setting is needed to read it.

The cache is keyed by `plan_id` alone, because the catalogue is the same
answer for every tenant on a plan. It holds one entry per plan the process has
been asked about, and those ids come from the database (an entitlement's
foreign key, or the fixed `background` id), so the key space is the catalogue
itself, refreshed in place, never grown by a request (failure-modes #6).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.adapters.persistence import tables
from dw_platform.application.plan_catalog import PlanCatalogPort, PlanLimits

# Thirty seconds, as the membership cache's TTL: how long a migration that changes a
# plan's numbers takes to reach every process (ticket 01, R1.1).
PLAN_LIMITS_TTL_SECONDS = 30

# Every field of `PlanLimits` is a column of the table, read by its own name, so a
# field added to one and not the other fails at import, not as a silent default.
_COLUMNS = tuple(tables.plan_limits.c[f.name] for f in dataclasses.fields(PlanLimits))


@dataclass(frozen=True)
class SqlPlanCatalog:
    """One row of `platform.plan_limits`, or `None` when the plan has none."""

    session_factory: async_sessionmaker[AsyncSession]

    async def limits(self, plan_id: str) -> PlanLimits | None:
        async with self.session_factory() as session, session.begin():
            row = (
                await session.execute(
                    sa.select(*_COLUMNS).where(tables.plan_limits.c.plan_id == plan_id)
                )
            ).first()
        if row is None:
            return None
        return PlanLimits(**row._asdict())


@dataclass
class CachingPlanCatalog:
    """Answers from memory for `ttl_seconds` after each read of a plan.

    A plan with no row is cached as missing too: it is refused either way, and
    asking the database again for every refused run would make the refusal the
    expensive path. A read that fails raises to the caller, so the run is not
    admitted, and the entry it would have refreshed is neither used nor kept
    alive: a stale number is a guess about the present (failure-modes #7).
    """

    inner: PlanCatalogPort
    clock: UtcClock
    ttl_seconds: int = PLAN_LIMITS_TTL_SECONDS
    _entries: dict[str, tuple[datetime, PlanLimits | None]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def limits(self, plan_id: str) -> PlanLimits | None:
        now = self.clock.now()
        cached = self._entries.get(plan_id)
        if cached is not None and now - cached[0] < timedelta(seconds=self.ttl_seconds):
            return cached[1]
        limits = await self.inner.limits(plan_id)
        self._entries[plan_id] = (now, limits)
        return limits
