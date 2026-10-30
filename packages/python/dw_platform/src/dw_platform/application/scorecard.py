"""A Digital Worker's scorecard, read from data rather than from what the DW
says of itself (digital-worker R7; YC122).

Three sources, each one aggregate statement, over a rolling window of `days`
times 24 hours ending now (R7.1): the DW's work items by `created_at`, its
`dw.decision` approvals by `decided_at`, and the model spend of the runs its
principal acted in by the run's `created_at` (R7.3 writes that spend on the
run row). Who may read it is who may read the DW: 404 before anything else.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, get_args

from dw_kernel.errors import DomainError
from dw_kernel.ports import UtcClock
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.digital_worker import DigitalWorker
from dw_platform.domain.work_item import WorkStatus

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 30

WORK_STATUSES: tuple[str, ...] = get_args(WorkStatus)


@dataclass(frozen=True, slots=True)
class ScorecardCounts:
    """What the three statements count. `items_by_status` names only the
    statuses that occur; the scorecard fills the rest with 0."""

    items_by_status: Mapping[str, int]
    done_alone: int
    handed_off: int
    approved_as_is: int
    approved_edited: int
    rejected: int
    model_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class Scorecard:
    dw_id: uuid.UUID
    days: int
    since: datetime
    counts: ScorecardCounts

    @property
    def items_total(self) -> int:
        return sum(self.counts.items_by_status.values())

    @property
    def items_by_status(self) -> dict[str, int]:
        return {status: self.counts.items_by_status.get(status, 0) for status in WORK_STATUSES}

    @property
    def done_alone_rate(self) -> float | None:
        """Of every item made in the window, the share the DW finished itself;
        None with no item, which is not a rate of 0."""
        return _share(self.counts.done_alone, self.items_total)

    @property
    def handed_off_rate(self) -> float | None:
        return _share(self.counts.handed_off, self.items_total)


def _share(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


class ScorecardRepositoryPort(Protocol):
    async def counts(
        self,
        context: AccessContext,
        *,
        dw_id: uuid.UUID,
        principal_id: uuid.UUID,
        since: datetime,
    ) -> ScorecardCounts:
        """The three aggregates under the caller's tenant and workspace."""
        ...


class DwReaderPort(Protocol):
    async def get(self, context: AccessContext, dw_id: uuid.UUID) -> DigitalWorker:
        """The DW, or 404 when the caller may not read it (R1.5)."""
        ...


@dataclass(frozen=True)
class ScorecardService:
    workers: DwReaderPort
    repo: ScorecardRepositoryPort
    clock: UtcClock

    async def scorecard(
        self, context: AccessContext, dw_id: uuid.UUID, *, days: int = DEFAULT_DAYS
    ) -> Scorecard:
        if not MIN_DAYS <= days <= MAX_DAYS:
            raise DomainError(
                f"days is {MIN_DAYS} to {MAX_DAYS}",
                details={"reason_code": "days_out_of_range", "days": days},
            )
        worker = await self.workers.get(context, dw_id)
        since = self.clock.now() - timedelta(hours=24 * days)
        counts = await self.repo.counts(
            context, dw_id=worker.id, principal_id=worker.principal_user_id, since=since
        )
        return Scorecard(dw_id=worker.id, days=days, since=since, counts=counts)


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "MIN_DAYS",
    "DwReaderPort",
    "Scorecard",
    "ScorecardCounts",
    "ScorecardRepositoryPort",
    "ScorecardService",
]
