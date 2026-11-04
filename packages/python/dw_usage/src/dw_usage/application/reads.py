"""The ledger's two readers from the first day: a run's usage and the
company's usage summary (usage-and-limits R3.5, R3.6, R3.12).

The summary is authorised here, before the store is asked anything: a caller
without `platform.usage.read` is refused and no row of `platform.usage_daily`
is read (R3.12). The key is of `scope_kind` `tenant`, held only at company
depth (`ck_tenant_role_permissions_depth_kind`), so its holder reads the whole
company, the company-level calls (no workspace) as their own group.

A run's usage is read after the caller's own run has been found in the caller's
workspace, by the route, as `GET /runs/{run_id}` does; this service sums the
records of exactly that `run_id` (M8: child runs by `root_run_id` are W2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

from dw_kernel.errors import DomainError
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import AuthorizationPort
from dw_usage.application.calendar import UsageCalendar
from dw_usage.application.ports import (
    GroupBy,
    RunUsageRow,
    SummaryFilter,
    SummaryRow,
    UsageReadPort,
)

__all__ = ["MAX_SUMMARY_DAYS", "USAGE_READ", "RunUsage", "UsageReads", "UsageSummary"]

USAGE_READ: Final = "platform.usage.read"
# The longest range one summary covers (M11): thirteen months and change, the
# ledger's own term.
MAX_SUMMARY_DAYS: Final = 400


@dataclass(frozen=True)
class RunUsage:
    run_id: UUID
    rows: list[RunUsageRow]

    @property
    def calls(self) -> int:
        return sum(row.calls for row in self.rows)

    @property
    def cost_usd(self) -> Decimal:
        return sum((row.cost_usd for row in self.rows), Decimal(0))


@dataclass(frozen=True)
class UsageSummary:
    first_day: date
    last_day: date
    timezone: str
    group_by: GroupBy
    groups: list[SummaryRow]


@dataclass(frozen=True)
class UsageReads:
    store: UsageReadPort
    calendar: UsageCalendar
    authz: AuthorizationPort
    clock: UtcClock

    async def run_usage(self, tenant_id: UUID, run_id: UUID) -> RunUsage:
        """The run's records summed by operation, model and cost source; empty
        for a run that has called no model yet (a total of zero, not a 404)."""
        return RunUsage(run_id=run_id, rows=await self.store.run_usage(tenant_id, run_id))

    async def summary(
        self,
        context: AccessContext,
        *,
        group_by: GroupBy,
        first_day: date | None = None,
        last_day: date | None = None,
        workspace_id: UUID | None = None,
        artifact_kind: str | None = None,
        artifact_id: UUID | None = None,
    ) -> UsageSummary:
        await self.authz.require(
            context=context,
            action=USAGE_READ,
            resource_type="usage_summary",
            resource_id=str(context.tenant_id),
        )
        month = await self.calendar.window_for(context.tenant_id, "month", self.clock.now())
        first = first_day or month.day
        last = last_day or _last_day(month.end, month.timezone)
        if last < first:
            raise DomainError("the summary range ends before it starts")
        if (last - first).days + 1 > MAX_SUMMARY_DAYS:
            raise DomainError(
                "the summary range is too long",
                details={"max_days": MAX_SUMMARY_DAYS},
            )
        groups = await self.store.summary(
            context.tenant_id,
            SummaryFilter(
                first_day=first,
                last_day=last,
                group_by=group_by,
                workspace_id=workspace_id,
                artifact_kind=artifact_kind,
                artifact_id=artifact_id,
            ),
        )
        return UsageSummary(
            first_day=first,
            last_day=last,
            timezone=month.timezone,
            group_by=group_by,
            groups=groups,
        )


def _last_day(end: datetime, timezone: str) -> date:
    """The local day before a window's exclusive end."""
    return (end.astimezone(ZoneInfo(timezone)) - timedelta(days=1)).date()
