"""The `usage_rollup` lane: today and yesterday of every company with recent
usage, recomputed into `platform.usage_daily` (usage-and-limits R3.5).

Each day is cut by `window_for` in the company's own time zone and handed to
SQL as `[start, end)`; a recompute replaces the day, so running twice gives the
same rows and a record settled late shows after the next pass. Finding the
companies is the lane's one cross-tenant read, under `app.worker_drain`; each
day is then written under that company's own tenant.

What is not recomputed (M1): a record landing more than a day late, and the
days before a company changes its time zone. Ticket 03's reaper writes the
only late records W1 has, inside a lease's lifetime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from dw_kernel.ports import UtcClock
from dw_usage.application.calendar import UsageCalendar
from dw_usage.application.ports import UsageRollupStorePort

__all__ = ["LOOKBACK", "UsageRollup"]

_LOG = logging.getLogger("dw_usage.rollup")

# Far enough back to hold the whole of yesterday in any time zone (UTC-12 to
# UTC+14), so a company is found whenever either of its two days has a record.
LOOKBACK: Final = timedelta(hours=50)


@dataclass(frozen=True)
class UsageRollup:
    store: UsageRollupStorePort
    calendar: UsageCalendar
    clock: UtcClock

    async def run_once(self) -> int:
        """One pass; the number of company-days recomputed. A company whose
        pass fails is logged and left for the next one; the others go on."""
        now = self.clock.now()
        done = 0
        for tenant_id in await self.store.tenants_with_usage_since(now - LOOKBACK):
            try:
                today = await self.calendar.window_for(tenant_id, "day", now)
                yesterday = await self.calendar.window_for(
                    tenant_id, "day", today.start - timedelta(microseconds=1)
                )
                for window in (yesterday, today):
                    await self.store.recompute_day(
                        tenant_id, window.day, window.start, window.end, now
                    )
                    done += 1
            except Exception:
                # Broad on purpose: one company's bad time zone or a failed
                # statement must not stop every other company's roll-up.
                _LOG.exception("usage roll-up failed for tenant %s", tenant_id)
        return done

    async def __call__(self) -> None:
        """The lane's consumer: one pass per tick."""
        done = await self.run_once()
        if done:
            _LOG.info("usage roll-up recomputed %d company-days", done)
