"""The lane that deletes tool claims past `expires_at` (runtime-hardening R6.7).

Its own module because it sets `app.worker_drain`: the API imports the claim
adapter, and the drain scan (`test_drain_setting_scan.py`) refuses a module the
API imports that sets it. Only the worker imports this one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.runtime_tables import tool_execution_claims

__all__ = ["SqlToolClaimRetention"]

logger = logging.getLogger("dw_agent_runtime.tool_claim_retention")

_SET_DRAIN = text("SELECT set_config('app.worker_drain', 'on', true)")


@dataclass(frozen=True)
class SqlToolClaimRetention:
    """Implements `dw_worker.consumers.retention.RetentionPrunePort` for claims (R6.7).

    A claim past `expires_at` guards nothing: the next call with its key takes it
    over (ADR-0108 decision 5), so the lane deletes it with no further term.
    What it guarded is not lost with it: a dispatch with no known outcome is
    answered from `platform.tool_executions`, which this lane never touches
    (R6.9). Housekeeping of operational rows, so it writes no audit and logs the
    count (ADR-0011 "Not applied").
    """

    session_factory: async_sessionmaker[AsyncSession]

    async def prune(self) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(_SET_DRAIN)
            removed = await session.execute(
                sa.delete(tool_execution_claims).where(
                    tool_execution_claims.c.expires_at < sa.func.now()
                )
            )
        logger.info(
            "retention removed expired tool claims",
            extra={"deleted": getattr(removed, "rowcount", 0)},
        )
