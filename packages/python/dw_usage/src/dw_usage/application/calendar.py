"""`window_for`: a company's period at a moment, in the company's time zone.

The one place a usage day or month is cut (ADR-0121 decision 9): the roll-up
lane, the usage summary's default range and the limits' counters of ticket 03
all ask it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from dw_usage.application.ports import TenantTimezonePort
from dw_usage.domain.windows import Window, WindowKind, window_bounds

__all__ = ["UsageCalendar"]


@dataclass(frozen=True)
class UsageCalendar:
    timezones: TenantTimezonePort

    async def window_for(self, tenant_id: UUID, window_kind: WindowKind, at: datetime) -> Window:
        return window_bounds(await self.timezones.timezone_of(tenant_id), window_kind, at)
