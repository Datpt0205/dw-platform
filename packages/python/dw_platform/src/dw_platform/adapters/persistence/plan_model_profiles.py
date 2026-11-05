"""`PlanModelProfilesPort` over `platform.plan_model_profiles`, and its
in-process cache (model-connections R2.1, R2.2, R2.6; ADR-0118 decision 1).

A global table like `platform.plan_limits`: the table is a global
catalogue written by migrations only, with no RLS and no tenant setting needed
to read it, so `dw_app` reads it on a session of its own. The answer is the set
of platform profile ids a plan lists; a plan with no rows lists none, and the
resolver refuses every platform profile for it.

The cache is keyed by `plan_id` alone, whose values come from the database (an
entitlement's foreign key, or the fixed `background` id), so the key space is
the catalogue itself (failure-modes #6). A read that fails raises to the
resolver, which refuses the call; it is never "every profile", and the entry it
would have refreshed is neither used nor kept alive (failure-modes #7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_kernel.ports import UtcClock
from dw_platform.adapters.persistence import tables

__all__ = ["PLAN_PROFILES_TTL_SECONDS", "CachingPlanModelProfiles", "SqlPlanModelProfiles"]

# Thirty seconds, as the membership cache's TTL: how long a migration that changes
# which profiles a plan lists takes to reach every process (model-connections 02).
PLAN_PROFILES_TTL_SECONDS = 30

_TABLE = tables.plan_model_profiles


class _PlanProfiles(Protocol):
    """`dw_agent_runtime.ports.PlanModelProfilesPort`, which both classes here
    satisfy; restated because the platform does not import the runtime."""

    async def allowed(self, plan_id: str) -> frozenset[str]: ...


@dataclass(frozen=True)
class SqlPlanModelProfiles:
    session_factory: async_sessionmaker[AsyncSession]

    async def allowed(self, plan_id: str) -> frozenset[str]:
        async with self.session_factory() as session, session.begin():
            rows = await session.scalars(
                sa.select(_TABLE.c.profile_id).where(_TABLE.c.plan_id == plan_id)
            )
            return frozenset(rows)


@dataclass
class CachingPlanModelProfiles:
    """Answers from memory for `ttl_seconds` after each read of a plan: how long
    a migration that changes a plan's list takes to reach every process."""

    inner: _PlanProfiles
    clock: UtcClock
    ttl_seconds: int = PLAN_PROFILES_TTL_SECONDS
    _entries: dict[str, tuple[datetime, frozenset[str]]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def allowed(self, plan_id: str) -> frozenset[str]:
        now = self.clock.now()
        cached = self._entries.get(plan_id)
        if cached is not None and now - cached[0] < timedelta(seconds=self.ttl_seconds):
            return cached[1]
        profiles = await self.inner.allowed(plan_id)
        self._entries[plan_id] = (now, profiles)
        return profiles
